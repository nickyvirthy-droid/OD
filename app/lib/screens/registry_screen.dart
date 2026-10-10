import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/od_api.dart';

/// Tela do Registro Mestre — aba "Verificar" (v1.24.0).
///
/// O dono cobrou (2026-10-09): "porque atualizou o APP se ele não possui
/// a tela de Registro Mestre". Mesma função do site
/// /site/verificacao.html, no app:
///
///   - consulta pública pelo ID GRAVADO na peça (tolerante a hífens e
///     espaços — o servidor normaliza);
///   - selo de autenticidade, foto do produto, coleção, status e o
///     USERNAME de quem tem a peça (nome real nunca — preço/notas nunca);
///   - sala de bate-papo da peça: qualquer um LÊ; quem TEM CONTA escreve
///     (401 sem conta → aviso para entrar pelo chat do ecossistema).
///     Polling de 4 s enquanto a peça está na tela.
class RegistryScreen extends StatefulWidget {
  final OdApi api;
  const RegistryScreen({super.key, required this.api});

  @override
  State<RegistryScreen> createState() => _RegistryScreenState();
}

class _RegistryScreenState extends State<RegistryScreen> {
  final _codigoCtrl = TextEditingController();
  OdRegistryItem? _peca;
  Uint8List? _foto;
  String? _erro;
  bool _verificando = false;

  // -- Sala de bate-papo da peça (polling de 4 s) --
  final List<OdRegistryMessage> _msgs = [];
  int _ultimoId = 0;
  Timer? _poller;
  final _msgsCtrl = ScrollController();
  final _chatCtrl = TextEditingController();
  bool _enviando = false;

  @override
  void dispose() {
    _poller?.cancel();
    _codigoCtrl.dispose();
    _chatCtrl.dispose();
    _msgsCtrl.dispose();
    super.dispose();
  }

  bool get _temConta =>
      widget.api.apiKey.isNotEmpty || widget.api.username.isNotEmpty;

  Future<void> _verificar() async {
    final cod = _codigoCtrl.text.trim();
    if (cod.isEmpty || _verificando) return;
    _poller?.cancel();
    setState(() {
      _verificando = true;
      _erro = null;
      _peca = null;
      _foto = null;
      _msgs.clear();
      _ultimoId = 0;
    });
    try {
      final peca = await widget.api.verifyPiece(cod);
      // Foto é pública (sem credencial); erro/ausência nunca derruba a tela.
      final foto = peca.photoUrl == null
          ? null
          : await widget.api.registryPhoto(cod);
      if (!mounted) return;
      setState(() {
        _peca = peca;
        _foto = foto;
        _verificando = false;
      });
      await _carregarMsgs();
      _poller = Timer.periodic(
        const Duration(seconds: 4),
        (_) => _carregarMsgs(),
      );
    } on OdApiError catch (e) {
      if (!mounted) return;
      setState(() {
        _erro = e.message;
        _verificando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _erro = 'Falha na verificação: $e';
        _verificando = false;
      });
    }
  }

  Future<void> _carregarMsgs() async {
    final peca = _peca;
    if (peca == null) return;
    try {
      final novas =
          await widget.api.registryChat(peca.publicId, since: _ultimoId);
      if (novas.isEmpty || !mounted) return;
      setState(() {
        _msgs.addAll(novas);
        _ultimoId = novas
            .map((m) => m.id)
            .reduce((a, b) => a > b ? a : b);
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_msgsCtrl.hasClients) {
          _msgsCtrl.jumpTo(_msgsCtrl.position.maxScrollExtent);
        }
      });
    } catch (_) {
      // Leitura pública no polling é best-effort: mantém o que já temos.
    }
  }

  Future<void> _enviar() async {
    final peca = _peca;
    final texto = _chatCtrl.text.trim();
    if (peca == null || texto.isEmpty || _enviando) return;
    setState(() => _enviando = true);
    try {
      final msg = await widget.api.registryChatPost(peca.publicId, texto);
      _chatCtrl.clear();
      if (!mounted) return;
      setState(() {
        _msgs.add(msg);
        if (msg.id > _ultimoId) _ultimoId = msg.id;
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_msgsCtrl.hasClients) {
          _msgsCtrl.jumpTo(_msgsCtrl.position.maxScrollExtent);
        }
      });
    } on OdApiError catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _enviando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(children: [
          Icon(Icons.workspace_premium, color: scheme.primary),
          const SizedBox(width: 8),
          Text('Registro Mestre',
              style: Theme.of(context).textTheme.titleMedium),
        ]),
        const SizedBox(height: 4),
        Text(
          'Digite o ID gravado na peça para conferir a autenticidade. '
          'Público, sem login — e não mostra preço nem dados privados.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 16),

        // -- Busca --
        Row(children: [
          Expanded(
            child: TextField(
              controller: _codigoCtrl,
              textInputAction: TextInputAction.search,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'ID da peça',
                hintText: 'OD-PROD-2026-0001 ou NV-ABI-7F3A',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.search),
              ),
              onSubmitted: (_) => _verificar(),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton(
            onPressed: _verificando ? null : _verificar,
            child: _verificando
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Verificar'),
          ),
        ]),
        const SizedBox(height: 6),
        Text(
          'Sem hífen também serve: odprod20260001 acha.',
          style: Theme.of(context).textTheme.bodySmall,
        ),

        if (_erro != null) ...[
          const SizedBox(height: 16),
          Card(
            color: scheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                Icon(Icons.cancel_outlined, color: scheme.onErrorContainer),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    _erro!,
                    style: TextStyle(color: scheme.onErrorContainer),
                  ),
                ),
              ]),
            ),
          ),
        ],

        if (_peca != null) ...[
          const SizedBox(height: 16),
          _cardPeca(context, scheme),
          const SizedBox(height: 16),
          _cardSala(context, scheme),
        ],
      ],
    );
  }

  Widget _cardPeca(BuildContext context, ColorScheme scheme) {
    final peca = _peca!;
    final (seloTexto, alerta) = peca.selo;
    final seloColor = alerta ? scheme.tertiary : scheme.primary;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Chip(
              visualDensity: VisualDensity.compact,
              backgroundColor: seloColor.withValues(alpha: 0.15),
              side: BorderSide(color: seloColor.withValues(alpha: 0.5)),
              label: Text('✓ $seloTexto',
                  style: TextStyle(
                      color: seloColor, fontWeight: FontWeight.bold)),
            ),
            const SizedBox(height: 12),
            if (_foto != null) ...[
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.memory(
                  _foto!,
                  height: 200,
                  width: double.infinity,
                  fit: BoxFit.cover,
                ),
              ),
              const SizedBox(height: 12),
            ],
            Text(peca.name,
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(
              [
                if (peca.collection != null) 'Coleção ${peca.collection}',
                peca.kind == 'publica' ? 'Linha pública' : 'Peça exclusiva',
              ].join(' · '),
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: [
              _campo(context, 'ID', peca.publicId),
              _campo(context, 'Código gravado', peca.engravedCode ?? '—'),
              _campo(context, 'Status', peca.statusLabel),
            ]),
            if (peca.registered && peca.ownerUsername != null) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: scheme.primaryContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'Esta peça tem dono: @${peca.ownerUsername} — '
                  'o username é público; o nome real, nunca.',
                  style: TextStyle(color: scheme.onPrimaryContainer),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _campo(BuildContext context, String rotulo, String valor) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(rotulo,
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(letterSpacing: 1.2)),
          Text(valor, style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  Widget _cardSala(BuildContext context, ColorScheme scheme) {
    final peca = _peca!;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('💬 Sala da peça',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              peca.status == 'registrada' && peca.ownerUsername != null
                  ? 'Quem tem esta peça é @${peca.ownerUsername}. '
                      'Converse: qualidade, detalhes, negociação direta.'
                  : 'Peça ainda sem dono registrado — quem responde aqui '
                      'é o ecossistema Omega Drakon.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            if (_msgs.isEmpty)
              Text(
                'Nenhuma mensagem ainda — seja o primeiro a falar.',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(fontStyle: FontStyle.italic),
              )
            else
              Container(
                height: 260,
                decoration: BoxDecoration(
                  color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: ListView.builder(
                  controller: _msgsCtrl,
                  padding: const EdgeInsets.all(8),
                  itemCount: _msgs.length,
                  itemBuilder: (context, i) {
                    final m = _msgs[i];
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '@${m.username} · '
                            '${m.createdAt.day.toString().padLeft(2, '0')}/'
                            '${m.createdAt.month.toString().padLeft(2, '0')} '
                            '${m.createdAt.hour.toString().padLeft(2, '0')}:'
                            '${m.createdAt.minute.toString().padLeft(2, '0')}',
                            style: Theme.of(context)
                                .textTheme
                                .labelSmall
                                ?.copyWith(color: scheme.primary),
                          ),
                          Text(m.text),
                        ],
                      ),
                    );
                  },
                ),
              ),
            const SizedBox(height: 12),
            if (_temConta)
              Row(children: [
                Expanded(
                  child: TextField(
                    controller: _chatCtrl,
                    maxLength: 2000,
                    decoration: const InputDecoration(
                      labelText: 'Mensagem',
                      border: OutlineInputBorder(),
                      counterText: '',
                    ),
                    onSubmitted: (_) => _enviar(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  onPressed: _enviando ? null : _enviar,
                  icon: _enviando
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.send),
                ),
              ])
            else
              Text(
                'Entre com sua conta (aba Config → conta) para conversar '
                'na sala da peça — qualquer pessoa com conta participa.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ),
      ),
    );
  }
}
