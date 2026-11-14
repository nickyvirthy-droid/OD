import 'dart:async';

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
///   - atualiza sozinha a cada 5 s enquanto a aba está aberta; fila
///     desligada no servidor aparece como aviso, não como lista vazia.
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
  Timer? _poller;

  static const _filtros = <String, String>{
    '': 'todas',
    'pending': 'pendentes',
    'running': 'rodando',
    'completed': 'concluídas',
    'failed': 'falhas',
    'dead_letter': 'dead letter',
  };

  @override
  void initState() {
    super.initState();
    _carregar();
    // A fila muda fora do app (chat/automações): reler de 5 em 5 s evita
    // depender de SSE só para esta aba.
    _poller = Timer.periodic(
      const Duration(seconds: 5),
      (_) => _carregar(silencioso: true),
    );
  }

  @override
  void dispose() {
    _poller?.cancel();
    super.dispose();
  }

  Future<void> _carregar({bool silencioso = false}) async {
    try {
      final tarefas = await widget.api.listTasks(limit: 200);
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
    // Mais recentes primeiro: o histórico é para olhar o que acabou de rodar.
    lista.sort((a, b) => b.createdTs.compareTo(a.createdTs));
    return lista;
  }

  String get _resumo {
    int contar(String status) => _tarefas.where((t) => t.status == status).length;
    final ativas = contar('pending') + contar('running');
    return '${contar('completed')} concluída(s) · $ativas ativa(s) · '
        '${contar('dead_letter')} dead letter · ${_tarefas.length} no total';
  }

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
                    const Text(
                      '↻ relê a cada 5 s',
                      style: TextStyle(fontSize: 11),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: 'Atualizar agora',
                onPressed: _carregar,
                icon: const Icon(Icons.refresh),
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
