import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../services/od_api.dart';

/// Tela de Tarefas — histórico da Task Queue (R1) com status e resultado.
///
/// Mostra a fila do SERVIDOR (pendente, rodando, concluída, falha e dead
/// letter) e o histórico de concluídas, que o servidor limita por
/// `OD_TASK_QUEUE_KEEP_COMPLETED` e poda sozinho.
///
///   - filtro por status, sem refazer a chamada (a lista já vem inteira);
///   - ⟳ reenfileira falha/dead letter como task NOVA;
///   - 🗑 apaga o registro terminal (task ativa responde 409 no servidor);
///   - **SSE ao vivo** (`/admin/tasks/events`) com fallback para polling
///     de 5 s e reconexão automática (mesmo contrato dos Downloads);
///   - fila desligada no servidor aparece como aviso, não como lista vazia.
class TasksScreen extends StatefulWidget {
  final OdApi api;
  const TasksScreen({super.key, required this.api});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  List<OdTask> _tarefas = [];
  String _filtro = '';
  String? _erro;
  bool _carregando = true;
  bool _ordenarPorConclusao = true; // default: mais recentes primeiro

  // -- Ao vivo (SSE) + fallback de polling + nova tentativa de assinatura --
  StreamSubscription<OdTaskEvent>? _sse;
  Timer? _poller;
  Timer? _reconectar;
  bool _sseAtivo = false;

  @override
  void initState() {
    super.initState();
    _carregar();
    _assinar();
  }

  @override
  void dispose() {
    _sse?.cancel();
    _poller?.cancel();
    _reconectar?.cancel();
    super.dispose();
  }

  // ------------------------------------------------------------------//
  // Dados                                                              //
  // ------------------------------------------------------------------//
  Future<void> _carregar({bool silencioso = false}) async {
    try {
      final tarefas = await widget.api.listTasks(
        limit: 200,
        sortByFinished: _ordenarPorConclusao,
      );
      if (!mounted) return;
      setState(() {
        _tarefas = tarefas;
        _erro = null;
        _carregando = false;
      });
    } catch (e) {
      if (!mounted) return;
      if (silencioso) return;
      setState(() {
        _erro = _descrever(e);
        _carregando = false;
      });
    }
  }

  void _assinar() {
    _sse?.cancel();
    _sse = widget.api.streamTasks().listen(
      (evento) {
        if (!mounted) return;
        // Voltou ao vivo: o polling e o reagendamento saem do caminho.
        _sseAtivo = true;
        _reconectar?.cancel();
        _reconectar = null;
        _poller?.cancel();
        _poller = null;
        _aplicar(evento);
      },
      onError: (_) => _sseCaiu(),
      onDone: () => _sseCaiu(),
    );
  }

  void _sseCaiu() {
    if (!mounted) return;
    _sseAtivo = false;
    _poller ??= Timer.periodic(const Duration(seconds: 5), (_) => _carregar());
    _carregar();
    _reconectar ??= Timer(const Duration(seconds: 15), () {
      _reconectar = null;
      if (mounted) _assinar();
    });
  }

  void _aplicar(OdTaskEvent evento) {
    setState(() {
      if (evento.evento == 'snapshot') {
        _tarefas
          ..clear()
          ..addAll(evento.tasks);
        _erro = null;
        return;
      }
      final task = evento.task;
      if (task == null) return;
      if (evento.evento == 'removido' || evento.evento == 'task_deleted') {
        _tarefas.removeWhere((t) => t.id == task.id);
      } else {
        _substituirLocal(task);
      }
      _erro = null;
    });
  }

  void _substituirLocal(OdTask task) {
    final i = _tarefas.indexWhere((t) => t.id == task.id);
    if (i >= 0) {
      _tarefas[i] = task;
    } else {
      _tarefas.add(task);
    }
  }

  // ------------------------------------------------------------------//
  // Ações                                                              //
  // ------------------------------------------------------------------//
  Future<void> _novaTarefa() async {
    // Abre diálogo simples para escolher action + payload JSON
    final actionCtrl = TextEditingController();
    final payloadCtrl = TextEditingController(text: '{}');
    final action = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Enfileirar tarefa'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: actionCtrl,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Action (do catálogo)',
                hintText: 'ex.: filesystem_write',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: payloadCtrl,
              decoration: const InputDecoration(
                labelText: 'Payload JSON (objeto)',
                hintText: '{"path": "data/x.txt", "content": "olá"}',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(actionCtrl.text.trim()),
            child: const Text('Enfileirar'),
          ),
        ],
      ),
    );
    if (action == null || action.isEmpty || !mounted) return;
    Map<String, dynamic> payload = {};
    final bruto = payloadCtrl.text.trim();
    if (bruto.isNotEmpty) {
      try {
        payload = jsonDecode(bruto) as Map<String, dynamic>;
      } catch (e) {
        // array/scalar/caixa alta de aspas: o cast falha ou o parser reclama
        _aviso('Payload deve ser um objeto JSON {…}: $e');
        return;
      }
    }
    // Payload vazio é VÁLIDO na API (actions sem parâmetros, ex.:
    // system_info) — o servidor faz `or {}`. Só objeto passa; `{}` roda.
    try {
      final criada = await widget.api.createTask(action, payload: payload);
      if (!mounted) return;
      setState(() => _tarefas = [..._tarefas, criada]);
      _aviso('✓ $action enfileirada (${criada.id})');
      // O SSE task_created já vai atualizar; o reload silencioso garante.
      await _carregar(silencioso: true);
    } catch (e) {
      _aviso(_descrever(e));
    }
  }

  Future<void> _retentar(OdTask tarefa) async {
    try {
      final nova = await widget.api.retryTask(tarefa.id);
      if (!mounted) return;
      setState(() => _tarefas = [..._tarefas, nova]);
      _aviso('Reenfileirada como ${nova.id}');
      await _carregar(silencioso: true);
    } catch (e) {
      _aviso(_descrever(e));
    }
  }

  Future<void> _apagar(OdTask tarefa) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Apagar registro?'),
        content: Text(
          'A tarefa "${tarefa.actionName}" sai do histórico. '
          'A action executada não é desfeita.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Voltar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Apagar'),
          ),
        ],
      ),
    );
    if (confirmar != true || !mounted) return;
    try {
      await widget.api.deleteTask(tarefa.id);
      if (!mounted) return;
      setState(() => _tarefas.removeWhere((t) => t.id == tarefa.id));
    } catch (e) {
      _aviso(_descrever(e));
    }
  }

  void _aviso(String texto) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(texto)));
  }

  static String _descrever(Object e) =>
      e is OdApiError ? e.message : 'Falha de rede ao falar com o servidor.';

  List<OdTask> get _filtradas {
    final lista = _filtro.isEmpty
        ? _tarefas
        : _tarefas.where((t) => t.status == _filtro).toList();
    // O servidor já ordena (created_ts para pendentes/rodando,
    // finished_ts para concluídas/falhas/dead_letter se _ordenarPorConclusao).
    // Mantemos a ordem recebida.
    return lista;
  }

  String get _resumo {
    int contar(String status) => _tarefas.where((t) => t.status == status).length;
    final ativas = contar('pending') + contar('running');
    return '${contar('completed')} concluída(s) · $ativas ativa(s) · '
        '${contar('dead_letter')} dead letter · ${_tarefas.length} no total';
  }

  static const _filtros = <String, String>{
    '': 'todas',
    'pending': 'pendentes',
    'running': 'rodando',
    'completed': 'concluídas',
    'failed': 'falhas',
    'dead_letter': 'dead letter',
  };

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final lista = _filtradas;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Tarefas do servidor',
                        style: tema.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(
                      _carregando ? 'Consultando a fila…' : _resumo,
                      style: tema.textTheme.bodySmall,
                    ),
                    Text(
                      _sseAtivo ? '📡 ao vivo (SSE)' : '↻ consultando (5 s)',
                      style: tema.textTheme.bodySmall?.copyWith(
                        color: _sseAtivo ? Colors.greenAccent : Colors.amber,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: 'Enfileirar tarefa',
                onPressed: _novaTarefa,
                icon: const Icon(Icons.add_task),
              ),
              IconButton(
                tooltip: 'Atualizar agora',
                onPressed: _carregar,
                icon: const Icon(Icons.refresh),
              ),
              IconButton(
                tooltip: _ordenarPorConclusao
                    ? 'Ordenar por data de criação (padrão)'
                    : 'Ordenar por data de conclusão (concluídas mais recentes)',
                onPressed: () => setState(() {
                  _ordenarPorConclusao = !_ordenarPorConclusao;
                  _carregar();
                }),
                icon: Icon(
                  _ordenarPorConclusao ? Icons.schedule : Icons.access_time,
                  color: _ordenarPorConclusao ? Colors.greenAccent : null,
                ),
              ),
            ],
          ),
        ),
        SizedBox(
          height: 36,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            children: _filtros.entries
                .map(
                  (f) => Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      label: Text(f.value),
                      selected: _filtro == f.key,
                      onSelected: (_) => setState(() => _filtro = f.key),
                    ),
                  ),
                )
                .toList(),
          ),
        ),
        if (_erro != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Text(
              _erro!,
              style: TextStyle(color: tema.colorScheme.error, fontSize: 12),
            ),
          ),
        Expanded(
          child: _carregando
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _carregar,
                  child: lista.isEmpty
                      ? _listaVazia(tema)
                      : ListView.builder(
                          physics: const AlwaysScrollableScrollPhysics(),
                          itemCount: lista.length,
                          itemBuilder: (context, i) => _tile(lista[i], tema),
                        ),
                ),
        ),
      ],
    );
  }

  Widget _listaVazia(ThemeData tema) {
    // Com erro (ex.: 503 da fila desligada) a mensagem do topo já explica:
    // não inventar "lista vazia" como se não houvesse tarefas.
    if (_erro != null) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          const SizedBox(height: 80),
          const Icon(Icons.cloud_off, size: 48),
          const SizedBox(height: 12),
          Text(
            'Sem dados da fila agora — veja o aviso acima.',
            textAlign: TextAlign.center,
            style: tema.textTheme.bodyMedium,
          ),
        ],
      );
    }
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        const SizedBox(height: 80),
        const Icon(Icons.task_alt, size: 48),
        const SizedBox(height: 12),
        Text(
          _filtro.isEmpty
              ? 'Nenhuma tarefa ainda.\nA fila enche por POST /admin/tasks '
                  '(chat/automações).'
              : 'Nenhuma tarefa com este status.',
          textAlign: TextAlign.center,
          style: tema.textTheme.bodyMedium,
        ),
      ],
    );
  }

  Widget _tile(OdTask tarefa, ThemeData tema) {
    final detalhe = tarefa.detalheLabel;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 6, 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    tarefa.actionName,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                _selo(tarefa, tema),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'tentativa ${tarefa.attempts}/${tarefa.maxRetries} · '
              '${tarefa.duracaoLabel} · ${_data(tarefa.createdTs)}',
              style: tema.textTheme.bodySmall,
            ),
            Text(
              tarefa.id,
              style: tema.textTheme.bodySmall?.copyWith(fontSize: 10),
              overflow: TextOverflow.ellipsis,
            ),
            if (detalhe.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  detalhe,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: tema.textTheme.bodySmall?.copyWith(
                    fontSize: 11,
                    color: tarefa.status == 'failed' ||
                            tarefa.status == 'dead_letter'
                        ? tema.colorScheme.error
                        : null,
                  ),
                ),
              ),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (tarefa.podeRetentar)
                  IconButton(
                    tooltip: 'Reenfileirar como task nova',
                    onPressed: () => _retentar(tarefa),
                    icon: const Icon(Icons.replay),
                  ),
                if (tarefa.terminal)
                  IconButton(
                    tooltip: 'Apagar registro',
                    onPressed: () => _apagar(tarefa),
                    icon: const Icon(Icons.delete_outline),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _selo(OdTask tarefa, ThemeData tema) {
    final (texto, cor) = switch (tarefa.status) {
      'running' => ('Rodando', Colors.greenAccent),
      'completed' => ('Concluída', Colors.greenAccent),
      'failed' => ('Falha', tema.colorScheme.error),
      'dead_letter' => ('Dead letter', tema.colorScheme.error),
      _ => ('Pendente', tema.colorScheme.primary),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: cor.withValues(alpha: 0.15),
        border: Border.all(color: cor.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(texto, style: TextStyle(color: cor, fontSize: 11)),
    );
  }

  static String _data(double ts) {
    if (ts <= 0) return '—';
    final quando =
        DateTime.fromMillisecondsSinceEpoch((ts * 1000).round()).toLocal();
    String d2(int n) => n.toString().padLeft(2, '0');
    return '${d2(quando.day)}/${d2(quando.month)} ${d2(quando.hour)}:'
        '${d2(quando.minute)}';
  }
}