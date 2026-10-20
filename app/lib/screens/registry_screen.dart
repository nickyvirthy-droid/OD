import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../services/od_api.dart';
import '../services/od_qr.dart';

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
///   - REGISTRO DO COMPRADOR (Etapa 4, 2026-10-15): quem tem o código
///     POSSE-… do cartão/QR da compra registra a peça no PRÓPRIO nome
///     (POST /registry/posse com conta) — quem tem o código é o dono.
///   - CÂMERA QR (v1.44.0): o mesmo cartão lido pela câmera do app
///     preenche o código sozinho (od_qr.dart + mobile_scanner).
class RegistryScreen extends StatefulWidget {
  final OdApi api;
  const RegistryScreen({super.key, required this.api});

  @override
  State<RegistryScreen> createState() => _RegistryScreenState();
}

class _RegistryScreenState extends State<RegistryScreen> {
  final _codigoCtrl = TextEditingController();
  final _posseCtrl = TextEditingController();
  OdRegistryItem? _peca;
  Uint8List? _foto;
  String? _erro;
  bool _verificando = false;
  bool _registrando = false;

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
    _posseCtrl.dispose();
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

  /// Registra a peça no nome de quem tem a conta com o código do QR
  /// (Etapa 4). Sucesso: mostra o selo novo consultando a peça certa.
  Future<void> _registrarPosse() async {
    final cod = _posseCtrl.text.trim();
    if (cod.isEmpty || _registrando) return;
    setState(() {
      _registrando = true;
    });
    try {
      final peca = await widget.api.registrarPosse(cod);
      _posseCtrl.clear();
      if (!mounted) return;
      setState(() {
        _registrando = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('✔ Registrada no seu nome: ${peca.name}')),
      );
      // Consulta a peça recém-registrada — vira o selo "registrada" +
      // a sala da peça já apontando para o novo dono (você).
      _codigoCtrl.text = peca.publicId;
      await _verificar();
    } on OdApiError catch (e) {
      if (!mounted) return;
      setState(() {
        _registrando = false;
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _registrando = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Falha no registro: $e')),
      );
    }
  }

  /// Lê o QR do cartão com a câmera (v1.44.0, "câmera QR" — a v2 da
  /// Etapa 4): abre o leitor em tela cheia e preenche sozinho o campo
  /// que antes o comprador colava à mão. QR de posse → campo de posse
  /// (ele confere e toca em Registrar — a decisão "quem tem o código é
  /// o dono" continua explícita); QR com ?codigo= → consulta pública
  /// direta. Câmera negada/ausente: aviso honesto no leitor, o campo
  /// de código nunca sai do ar.
  Future<void> _abrirLeitorQr() async {
    final leitura = await Navigator.of(context).push<OdQrLeitura>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => const _LeitorQrTela(),
      ),
    );
    if (!mounted || leitura == null || leitura.vazio) return;
    if (leitura.posse != null) {
      setState(() => _posseCtrl.text = leitura.posse!);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            '✔ QR lido — código de posse preenchido. Confira e toque em Registrar.',
          ),
        ),
      );
    } else if (leitura.codigo != null) {
      setState(() => _codigoCtrl.text = leitura.codigo!);
      await _verificar();
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
                hintText: 'NV-SJ-2026-0001 ou NV-ABI-7F3A',
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

        const SizedBox(height: 16),
        _cardPosse(context, scheme),

        if (_peca != null) ...[
          const SizedBox(height: 16),
          _cardPeca(context, scheme),
          const SizedBox(height: 16),
          _cardSala(context, scheme),
        ],
      ],
    );
  }

  /// Card "Registrar minha peça" (Etapa 4): o comprador cola o código
  /// POSSE-… do cartão QR e a peça passa a constar com o username dele.
  /// Sem conta → instrução (a decisão do dono: registro exige cadastro).
  Widget _cardPosse(BuildContext context, ColorScheme scheme) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(Icons.qr_code_2, color: scheme.primary, size: 20),
              const SizedBox(width: 8),
              Text('Registrar minha peça',
                  style: Theme.of(context).textTheme.titleMedium),
            ]),
            const SizedBox(height: 4),
            Text(
              'Veio com a peça um cartão QR? Quem TEM o código é o dono: '
              'aponte a câmera (botão 📷) ou cole abaixo o código e a '
              'peça registra no SEU nome (aparece seu username na '
              'consulta pública — nome real, nunca).',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            if (!_temConta)
              Text(
                'Sem conta ainda? Entre ou crie a sua em Config → conta '
                '— o registro fica no seu nome a partir daí.',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(fontStyle: FontStyle.italic),
              )
            else
              Row(children: [
                Expanded(
                  child: TextField(
                    controller: _posseCtrl,
                    autocorrect: false,
                    textCapitalization: TextCapitalization.characters,
                    decoration: const InputDecoration(
                      labelText: 'Código de posse',
                      hintText: 'POSSE-XXXX-XXXX-XXXX-XXXX',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.key),
                    ),
                    onSubmitted: (_) => _registrarPosse(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filledTonal(
                  onPressed: _abrirLeitorQr,
                  tooltip: 'Ler QR com a câmera',
                  icon: const Icon(Icons.qr_code_scanner),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _registrando ? null : _registrarPosse,
                  child: _registrando
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Registrar'),
                ),
              ]),
          ],
        ),
      ),
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

/// Leitor de QR em tela cheia (v1.44.0, "câmera QR").
///
/// Só faz UMA coisa: devolver a [OdQrLeitura] do primeiro QR do
/// Registro Mestre que aparecer na câmera (pop com o resultado). QR de
/// outro assunto é ignorado e a leitura segue — pode ter sido engano de
/// mira. Sem permissão ou sem câmera, o `errorBuilder` mostra o aviso
/// honesto na própria tela: o caminho principal (digitar o código)
/// nunca trava por isto.
class _LeitorQrTela extends StatefulWidget {
  const _LeitorQrTela();

  @override
  State<_LeitorQrTela> createState() => _LeitorQrTelaState();
}

class _LeitorQrTelaState extends State<_LeitorQrTela> {
  /// Trava anti-rafale: o `onDetect` dispara várias vezes por segundo
  /// enquanto o QR está na mira — o primeiro que prestar fecha a tela.
  bool _lido = false;

  void _aoDetectar(BarcodeCapture captura) {
    if (_lido || !mounted) return;
    for (final barcode in captura.barcodes) {
      final texto = barcode.rawValue;
      if (texto == null || texto.trim().isEmpty) continue;
      final leitura = extrairCodigoQr(texto);
      if (leitura == null || leitura.vazio) continue; // QR alheio: segue
      _lido = true;
      Navigator.of(context).pop(leitura);
      return;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: const Text('Ler QR do cartão'),
      ),
      body: Stack(
        alignment: Alignment.center,
        children: [
          MobileScanner(
            onDetect: _aoDetectar,
            errorBuilder: (context, erro) {
              final semPermissao =
                  erro.errorCode == MobileScannerErrorCode.permissionDenied;
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.no_photography,
                          color: Colors.white54, size: 44),
                      const SizedBox(height: 14),
                      Text(
                        semPermissao
                            ? 'Sem permissão de câmera. Libere nos ajustes do '
                                'app ou digite o código na mão — nada trava.'
                            : 'Não deu para abrir a câmera neste aparelho '
                                '(${erro.errorCode.name}). Digite o código na '
                                'mão — nada trava.',
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Colors.white70),
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
          // Retículo de mira — moldura branca semitransparente.
          IgnorePointer(
            child: Container(
              width: 250,
              height: 250,
              decoration: BoxDecoration(
                border: Border.all(color: Colors.white70, width: 2),
                borderRadius: BorderRadius.circular(18),
              ),
            ),
          ),
          const Positioned(
            left: 24,
            right: 24,
            bottom: 36,
            child: Text(
              'Aponte para o QR do cartão da compra — '
              'QR de outro assunto é ignorado.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white70),
            ),
          ),
        ],
      ),
    );
  }
}
