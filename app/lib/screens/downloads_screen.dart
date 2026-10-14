import 'dart:async';

import 'package:flutter/material.dart';

import '../services/od_api.dart';

/// Tela de Downloads — aba "Downloads" (Parte D do NOMAD).
///
/// Mostra a fila de downloads do SERVIDOR (modelos, datasets, documentos
/// grandes), nunca da memória do celular:
///
///   - progresso AO VIVO por SSE (`/admin/downloads/events`): cada
///     transição chega empurrada; se o stream cair (restart do od-core,
///     troca de rota), a tela cai para polling de 5 s e tenta reassinar
///     (mesmo contrato do chat, que cai do WebSocket para o REST);
///   - enfileirar por URL com destino opcional — o servidor valida e
///     DEDUPLICA (mesma URL+destino ativa volta com o mesmo id);
///   - cancelar preserva o parcial no servidor (re-enfileirar retoma);
///   - apagar registro só de job terminado (arquivo em disco intocado).
class DownloadsScreen extends StatefulWidget {
  final OdApi api;
  const DownloadsScreen({super.key, required this.api});

  @override
  State<DownloadsScreen> createState() => _DownloadsScreenState();
}

class _DownloadsScreenState extends State<DownloadsScreen> {
  final List<OdDownload> _jobs = [];
  OdDownloadsResumo? _resumo;
  String? _erro;
  bool _carregando = true;

  // Campos do diálogo de enfileirar: vivem no Estado (e não locais) porque
  // o TextFielde da rota de diálogo ainda anima a SAÍDA depois do pop —
  // um controller local seria disposed no meio dessa animação.
  final _urlCtrl = TextEditingController();
  final _destinoCtrl = TextEditingController();

  // -- Ao vivo (SSE) + fallback de polling + nova tentativa de assinatura --
  StreamSubscription<OdDownloadEvent>? _sse;
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
    _urlCtrl.dispose();
    _destinoCtrl.dispose();
    super.dispose();
  }

  // ------------------------------------------------------------------//
  // Dados                                                              //
  // ------------------------------------------------------------------//
  Future<void> _carregar() async {
    try {
      final fila = await widget.api.listDownloads();
      if (!mounted) return;
      setState(() {
        _jobs
          ..clear()
          ..addAll(fila.jobs);
        _resumo = fila.resumo;
        _erro = null;
        _carregando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _erro = _descrever(e);
        _carregando = false;
      });
    }
  }

  void _assinar() {
    _sse?.cancel();
    _sse = widget.api.streamDownloads().listen(
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
    _poller ??=
        Timer.periodic(const Duration(seconds: 5), (_) => _carregar());
    _carregar();
    _reconectar ??= Timer(const Duration(seconds: 15), () {
      _reconectar = null;
      if (mounted) _assinar();
    });
  }

  void _aplicar(OdDownloadEvent evento) {
    setState(() {
      if (evento.evento == 'snapshot') {
        _jobs
          ..clear()
          ..addAll(evento.jobs);
        _resumo = evento.resumo ?? _resumoDaLista();
        _erro = null;
        return;
      }
      final job = evento.job;
      if (job == null) return;
      if (evento.evento == 'removido') {
        _jobs.removeWhere((j) => j.id == job.id);
      } else {
        _substituirLocal(job);
      }
      _resumo = _resumoDaLista();
      _erro = null;
    });
  }

  void _substituirLocal(OdDownload job) {
    final i = _jobs.indexWhere((j) => j.id == job.id);
    if (i >= 0) {
      _jobs[i] = job;
    } else {
      _jobs.add(job);
    }
  }

  /// Resumo recalculado na tela: nunca fica defasado entre um evento e
  /// outro (o snapshot do servidor confere no próximo reload).
  OdDownloadsResumo _resumoDaLista() {
    int contar(String status) => _jobs.where((j) => j.status == status).length;
    final ativas = contar('na_fila') + contar('baixando') + contar('aguardando');
    return OdDownloadsResumo(
      total: _jobs.length,
      ativas: ativas,
      naFila: contar('na_fila'),
      baixando: contar('baixando'),
      aguardando: contar('aguardando'),
      concluidos: contar('concluido'),
      erros: contar('erro'),
      cancelados: contar('cancelado'),
      bytesBaixados: _jobs.fold(0, (soma, j) => soma + j.bytesFeitos),
    );
  }

  // ------------------------------------------------------------------//
  // Ações                                                              //
  // ------------------------------------------------------------------//
  Future<void> _novoDownload() async {
    _urlCtrl.clear();
    _destinoCtrl.clear();
    final job = await showDialog<OdDownload>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Baixar arquivo'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _urlCtrl,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'URL (https://…)',
                hintText: 'https://…/modelo.gguf',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _destinoCtrl,
              decoration: const InputDecoration(
                labelText: 'Destino (opcional)',
                hintText: 'subpasta/arquivo.bin',
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
            onPressed: () => Navigator.of(context).pop(
              OdDownload(
                id: '',
                url: _urlCtrl.text.trim(),
                destino: _destinoCtrl.text.trim(),
                nome: '',
                status: '',
                bytesFeitos: 0,
                bytesTotal: -1,
                pct: null,
                tentativas: 0,
                maxTentativas: 0,
                erro: '',
                sha256: '',
                sha256Real: '',
              ),
            ),
            child: const Text('Baixar'),
          ),
        ],
      ),
    );
    if (job == null || !mounted || job.url.isEmpty) return;
    try {
      final criado = await widget.api.createDownload(
        url: job.url,
        destino: job.destino,
      );
      if (!mounted) return;
      setState(() {
        _substituirLocal(criado);
        _resumo = _resumoDaLista();
      });
      _aviso('Enfileirado: ${criado.id} — acompanhe aqui mesmo.');
    } catch (e) {
      _aviso(_descrever(e));
    }
  }

  Future<void> _cancelar(OdDownload job) async {
    try {
      final cancelado = await widget.api.cancelDownload(job.id);
      if (!mounted) return;
      setState(() {
        _substituirLocal(cancelado);
        _resumo = _resumoDaLista();
      });
    } catch (e) {
      _aviso(_descrever(e));
    }
  }

  Future<void> _apagar(OdDownload job) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Apagar registro?'),
        content: Text(
          'O registro de "${job.nome}" sai da fila. O arquivo em disco '
          'não é mexido.',
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
      await widget.api.deleteDownload(job.id);
      if (!mounted) return;
      setState(() {
        _jobs.removeWhere((j) => j.id == job.id);
        _resumo = _resumoDaLista();
      });
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

  // ------------------------------------------------------------------//
  // UI                                                                 //
  // ------------------------------------------------------------------//
  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
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
                    Text('Downloads do servidor',
                        style: tema.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(
                      _resumo == null
                          ? 'Consultando a fila…'
                          : '${_resumo!.ativas} ativa(s) · '
                              '${_resumo!.concluidos} concluído(s) · '
                              '${_resumo!.erros} erro(s) · '
                              '${formatarBytes(_resumo!.bytesBaixados)}',
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
                tooltip: 'Atualizar',
                onPressed: _carregar,
                icon: const Icon(Icons.refresh),
              ),
              FilledButton.icon(
                onPressed: _novoDownload,
                icon: const Icon(Icons.download),
                label: const Text('Baixar'),
              ),
            ],
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
                  child: _jobs.isEmpty
                      ? _listaVazia(tema)
                      : ListView.builder(
                          physics: const AlwaysScrollableScrollPhysics(),
                          itemCount: _jobs.length,
                          itemBuilder: (context, i) => _tile(_jobs[i], tema),
                        ),
                ),
        ),
      ],
    );
  }

  Widget _listaVazia(ThemeData tema) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        const SizedBox(height: 80),
        const Icon(Icons.download_outlined, size: 48),
        const SizedBox(height: 12),
        Text(
          'Nenhum download na fila.\nToque em "Baixar" e cole a URL de '
          'um modelo, dataset ou documento.',
          textAlign: TextAlign.center,
          style: tema.textTheme.bodyMedium,
        ),
      ],
    );
  }

  Widget _tile(OdDownload job, ThemeData tema) {
    final mostrandoBarra =
        job.status == 'baixando' || job.status == 'concluido';
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
                    job.nome.isEmpty ? job.url : job.nome,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                _selo(job, tema),
              ],
            ),
            if (mostrandoBarra) ...[
              const SizedBox(height: 8),
              LinearProgressIndicator(value: job.pct),
            ],
            const SizedBox(height: 6),
            Text(
              '${job.statusLabel} · ${job.bytesLabel}'
              '${job.tentativas > 1 ? ' · tentativa ${job.tentativas}/${job.maxTentativas}' : ''}'
              '${job.pctLabel.isNotEmpty ? ' · ${job.pctLabel}' : ''}',
              style: tema.textTheme.bodySmall,
            ),
            if (job.erro.isNotEmpty)
              Text(
                job.erro,
                style: tema.textTheme.bodySmall
                    ?.copyWith(color: tema.colorScheme.error),
              ),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (job.ativo)
                  IconButton(
                    tooltip: 'Cancelar (o parcial fica guardado)',
                    onPressed: () => _cancelar(job),
                    icon: const Icon(Icons.cancel_outlined),
                  ),
                if (job.terminal)
                  IconButton(
                    tooltip: 'Apagar registro',
                    onPressed: () => _apagar(job),
                    icon: const Icon(Icons.delete_outline),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _selo(OdDownload job, ThemeData tema) {
    final (texto, cor) = switch (job.status) {
      'baixando' => ('Baixando', Colors.greenAccent),
      'concluido' => ('Concluído', Colors.greenAccent),
      'erro' => ('Erro', tema.colorScheme.error),
      'cancelado' => ('Cancelado', Colors.amber),
      'aguardando' => ('Retry', Colors.amber),
      _ => ('Na fila', tema.colorScheme.primary),
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
}
