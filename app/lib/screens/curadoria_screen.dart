import 'package:flutter/material.dart';

import '../services/od_api.dart';

/// Tela "Curadoria do acervo" — a mesma curadoria do painel `/admin` e da
/// página `/radio-pro`, agora no celular (pedido do dono, 17/11).
///
/// O que dá para fazer (tudo atrás do papel admin no servidor):
/// - **Excluir** a faixa do acervo (disco + banco + playlists). Excluir NÃO
///   bloqueia: se alguém pedir de novo, ela pode voltar — ordem do dono de
///   17/11 ("posso apagar simplesmente por achar uma versão melhor").
/// - **Excluir e bloquear** de uma vez, ou **bloquear** sem apagar.
/// - **Desbloquear** uma faixa da lista negra.
/// - **Liberar como exceção** uma música de cantor bloqueado (o cantor segue
///   bloqueado, mas essa música não é apagada depois de tocar).
///
/// A tela é empurrada a partir do card do Painel: não virou nona aba de
/// propósito — o rodapé do app já está cheio e a curadoria é coisa de dono.
class CuradoriaScreen extends StatefulWidget {
  final OdApi api;

  const CuradoriaScreen({super.key, required this.api});

  @override
  State<CuradoriaScreen> createState() => _CuradoriaScreenState();
}

class _CuradoriaScreenState extends State<CuradoriaScreen> {
  final TextEditingController _busca = TextEditingController();
  OdCuradoria? _dados;
  String? _erro;
  bool _carregando = true;
  bool _ocupado = false;

  @override
  void initState() {
    super.initState();
    _carregar();
  }

  @override
  void dispose() {
    _busca.dispose();
    super.dispose();
  }

  Future<void> _carregar({bool silencioso = false}) async {
    if (!silencioso) {
      setState(() {
        _carregando = true;
        _erro = null;
      });
    }
    try {
      final dados = await widget.api.buscarCuradoria(termo: _busca.text);
      if (!mounted) return;
      setState(() {
        _dados = dados;
        _erro = null;
        _carregando = false;
      });
    } on OdApiError catch (e) {
      if (!mounted) return;
      setState(() {
        _erro = e.message;
        _carregando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _erro = 'Falha ao carregar a curadoria: $e';
        _carregando = false;
      });
    }
  }

  void _snack(String texto) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(texto)));
  }

  /// Roda uma ação e repinta com o bloco que o servidor devolveu.
  Future<void> _acao(
    String rotulo,
    Future<OdCuradoria> Function() chamada,
  ) async {
    if (_ocupado) return;
    setState(() => _ocupado = true);
    try {
      final dados = await chamada();
      if (!mounted) return;
      setState(() {
        _dados = dados;
        _erro = null;
      });
      _snack(rotulo);
    } on OdApiError catch (e) {
      _snack(e.message);
      await _carregar(silencioso: true);
    } catch (e) {
      _snack('Falha: $e');
    } finally {
      if (mounted) setState(() => _ocupado = false);
    }
  }

  Future<bool> _confirmar(String titulo, String texto, String botao) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(titulo),
        content: Text(texto),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(botao),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _excluir(OdMusicaAcervo musica, {required bool bloquear}) async {
    final ok = await _confirmar(
      bloquear ? 'Excluir e bloquear?' : 'Excluir do acervo?',
      '"${musica.nome}" sai do disco, do acervo e das playlists.\n\n'
          '${bloquear ? 'E fica BLOQUEADA: não volta nem se alguém pedir de novo.' : 'Excluir não bloqueia: se alguém pedir de novo, ela pode ser baixada outra vez (útil quando você apaga só para pegar uma versão melhor).'}',
      bloquear ? 'Excluir e bloquear' : 'Excluir',
    );
    if (!ok) return;
    await _acao(
      bloquear ? 'Faixa excluída e bloqueada.' : 'Faixa excluída do acervo.',
      () => widget.api
          .excluirMusicaDoAcervo(musica.caminho, bloquear: bloquear),
    );
  }

  Future<void> _bloquear(OdMusicaAcervo musica) async {
    await _acao(
      'Música bloqueada — não toca mais.',
      () => widget.api.bloquearMusica(musica.artista, musica.titulo),
    );
  }

  Future<void> _liberarExcecao(OdMusicaAcervo musica) async {
    await _acao(
      'Música liberada — o cantor segue bloqueado, mas esta fica.',
      () => widget.api.adicionarExcecao(musica.artista, musica.titulo),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final dados = _dados;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Curadoria do acervo'),
        actions: [
          IconButton(
            tooltip: 'Recarregar',
            icon: const Icon(Icons.refresh),
            onPressed: _ocupado ? null : () => _carregar(),
          ),
        ],
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => _carregar(silencioso: true),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            children: [
              TextField(
                controller: _busca,
                textInputAction: TextInputAction.search,
                onSubmitted: (_) => _carregar(),
                decoration: InputDecoration(
                  labelText: 'Buscar por artista ou música',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: IconButton(
                    tooltip: 'Buscar',
                    icon: const Icon(Icons.arrow_forward),
                    onPressed: _ocupado ? null : () => _carregar(),
                  ),
                ),
              ),
              if (_carregando)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: CircularProgressIndicator()),
                ),
              if (_erro != null)
                Card(
                  child: ListTile(
                    leading: Icon(Icons.error_outline,
                        color: tema.colorScheme.error),
                    title: Text(_erro!),
                    trailing: TextButton(
                      onPressed: () => _carregar(),
                      child: const Text('Tentar'),
                    ),
                  ),
                ),
              if (dados != null) ..._secoes(tema, dados),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _secoes(ThemeData tema, OdCuradoria dados) => [
        _cabecalho('Acervo (${dados.musicas.length})'),
        if (dados.musicas.isEmpty)
          const ListTile(
            dense: true,
            title: Text('Nenhuma música encontrada.'),
          ),
        for (final musica in dados.musicas) _itemAcervo(tema, musica),
        _cabecalho('Músicas bloqueadas (${dados.bloqueadas.length})'),
        if (dados.bloqueadas.isEmpty)
          const ListTile(
            dense: true,
            title: Text('Nenhuma música bloqueada.'),
          ),
        for (final par in dados.bloqueadas)
          ListTile(
            dense: true,
            leading: const Icon(Icons.block),
            title: Text(par.nome),
            trailing: IconButton(
              tooltip: 'Desbloquear',
              icon: const Icon(Icons.lock_open),
              onPressed: _ocupado
                  ? null
                  : () => _acao(
                        '"${par.nome}" pode tocar de novo.',
                        () => widget.api
                            .desbloquearMusica(par.artista, par.titulo),
                      ),
            ),
          ),
        _cabecalho('Exceções de cantores bloqueados '
            '(${dados.excecoes.length})'),
        if (dados.excecoes.isEmpty)
          const ListTile(
            dense: true,
            title: Text('Nenhuma exceção — todo cantor bloqueado tem as '
                'músicas apagadas depois de tocar.'),
          ),
        for (final par in dados.excecoes)
          ListTile(
            dense: true,
            leading: const Icon(Icons.verified_outlined),
            title: Text(par.nome),
            trailing: IconButton(
              tooltip: 'Tirar a exceção',
              icon: const Icon(Icons.remove_circle_outline),
              onPressed: _ocupado
                  ? null
                  : () => _acao(
                        'Exceção removida.',
                        () => widget.api
                            .removerExcecao(par.artista, par.titulo),
                      ),
            ),
          ),
      ];

  Widget _cabecalho(String texto) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 18, 4, 4),
        child: Text(
          texto,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w600),
        ),
      );

  Widget _itemAcervo(ThemeData tema, OdMusicaAcervo musica) {
    final bloqueada = musica.bloqueada;
    return ListTile(
      contentPadding: const EdgeInsets.only(left: 4),
      title: Text(musica.nome, style: tema.textTheme.bodyMedium),
      subtitle: Row(
        children: [
          if (musica.selo.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(right: 8),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                border: Border.all(color: tema.colorScheme.error),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                musica.selo,
                style: tema.textTheme.labelSmall
                    ?.copyWith(color: tema.colorScheme.error),
              ),
            ),
          Expanded(
            child: Text(
              musica.caminho,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: tema.textTheme.bodySmall
                  ?.copyWith(color: tema.colorScheme.onSurfaceVariant),
            ),
          ),
        ],
      ),
      trailing: PopupMenuButton<String>(
        enabled: !_ocupado,
        tooltip: 'Ações',
        onSelected: (acao) {
          switch (acao) {
            case 'excluir':
              _excluir(musica, bloquear: false);
            case 'excluir_bloquear':
              _excluir(musica, bloquear: true);
            case 'bloquear':
              _bloquear(musica);
            case 'excecao':
              _liberarExcecao(musica);
          }
        },
        itemBuilder: (_) => [
          const PopupMenuItem(
            value: 'excluir',
            child: Text('Excluir do acervo (pode voltar num pedido)'),
          ),
          const PopupMenuItem(
            value: 'excluir_bloquear',
            child: Text('Excluir e bloquear'),
          ),
          if (!bloqueada)
            const PopupMenuItem(
              value: 'bloquear',
              child: Text('Bloquear a música (apaga depois de tocar)'),
            ),
          if (musica.artistaBloqueado)
            const PopupMenuItem(
              value: 'excecao',
              child: Text('Liberar esta música do cantor bloqueado'),
            ),
        ],
      ),
    );
  }
}
