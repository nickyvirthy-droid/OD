/// OmegaDrakon — leitura de QR do Registro Mestre (v1.44.0, "câmera QR").
///
/// Contrato (Etapa 4 → v2): o QR impresso no cartão da compra carrega a
/// URL absoluta da verificação pública —
///
///     {base}/site/verificacao.html?posse=POSSE-XXXX-XXXX-XXXX-XXXX
///
/// O MESMO QR vale em qualquer base (LAN, tailnet, funnel ou DDNS — o
/// servidor gera a URL com `public_url`), então a leitura NÃO olha o
/// host: só o parâmetro. O app lê com a câmera (`mobile_scanner`) e
/// preenche sozinho o campo de posse — o comprador não digita nada.
///
/// Por completeza também aceita:
///   - `?codigo=NV-SJ-…` → leva direto à consulta pública da peça;
///   - texto cru `POSSE-XXXX-…` (quem fotografa/digita o código do
///     cartão sem passar pela URL).
///
/// Função PURA de propósito: testável em `flutter test` (VM sem
/// plataforma de câmera/imagem). Espelha o formato do servidor
/// (core/registry.py: `POSSE-` + 16 hex em 4 grupos de 4; o servidor
/// normaliza maiúsculo sem hífens — a forma canônica daqui é só
/// legibilidade do campo, o aceito é o dele).
library;

/// Resultado de uma leitura: tem posse, tem código gravado — ou é QR
/// alheio ([vazio], a tela ignora e continua apontando a câmera).
class OdQrLeitura {
  const OdQrLeitura({this.posse, this.codigo});

  /// `POSSE-XXXX-XXXX-XXXX-XXXX` — código do cartão (registro no nome
  /// de quem tem o QR).
  final String? posse;

  /// ID/código gravado na peça (consulta pública de autenticidade).
  final String? codigo;

  bool get vazio => posse == null && codigo == null;
}

// POSSE- + 16 hex em 4 grupos de 4 (core/registry.py — 64 bits de
// `secrets`; case-insensitive porque o app aceita o que a pessoa
// fotografar).
final RegExp _posseRe =
    RegExp(r'POSSE-[0-9A-F]{4}(?:-[0-9A-F]{4}){3}', caseSensitive: false);

/// Extrai o que interessa de um texto vindo da câmera. Retorna `null`
/// quando o QR não é do Registro Mestre (a tela avisa na dica e segue
/// lendo — pode ter capturado um QR de outra coisa por engano).
OdQrLeitura? extrairCodigoQr(String texto) {
  final bruto = texto.trim();
  if (bruto.isEmpty) return null;

  // 1) URL da verificação pública (?posse=… ou ?codigo=…).
  final uri = Uri.tryParse(bruto);
  if (uri != null && uri.hasQuery) {
    final posse = uri.queryParameters['posse']?.trim();
    if (posse != null && posse.isNotEmpty) {
      return OdQrLeitura(posse: _canonicoPosse(posse));
    }
    final codigo = uri.queryParameters['codigo']?.trim();
    if (codigo != null && codigo.isNotEmpty) {
      return OdQrLeitura(codigo: codigo.toUpperCase());
    }
  }

  // 2) Texto cru com o código POSSE (sem URL).
  final m = _posseRe.firstMatch(bruto);
  if (m != null) return OdQrLeitura(posse: _canonicoPosse(m.group(0)!));

  return null;
}

/// Forma canônica do código de posse: maiúsculo com hífens de 4 em 4
/// (do jeito que o cartão imprime). Corpo fora do formato 16 hex volta
/// em maiúsculas cruas — quem valida o código é o servidor, com a
/// tolerância dele (sem hífen/espaço também serve).
String _canonicoPosse(String codigo) {
  final limpo = codigo.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
  final corpo = limpo.startsWith('POSSE') ? limpo.substring(5) : limpo;
  if (corpo.length != 16) return codigo.trim().toUpperCase();
  final grupos = <String>[
    for (var i = 0; i < 16; i += 4) corpo.substring(i, i + 4),
  ];
  return 'POSSE-${grupos.join('-')}';
}
