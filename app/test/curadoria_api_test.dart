/// OmegaDrakon • TESTES — Curadoria do acervo (cliente REST, 17/11)
///
/// O app é o CLIENTE de `/api/radio/musicas*`: aqui prova o contrato de cada
/// rota (método, corpo, query), a leitura das três listas e as mensagens de
/// erro que o dono lê na tela — inclusive o 403 de conta que não é admin.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/services/od_api.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

const _acervo = {
  'musicas': [
    {
      'caminho': 'acervo/Outros/Annita - Envolver.mp3',
      'artista': 'Annita',
      'titulo': 'Envolver',
      'bloqueada': true,
      'artista_bloqueado': false,
    },
    {
      'caminho': 'acervo/Gospel/Pregador - Fogo.mp3',
      'artista': 'Pregador',
      'titulo': 'Fogo',
      'bloqueada': false,
      'artista_bloqueado': true,
    },
  ],
  'bloqueadas': [
    {'artista': 'Annita', 'titulo': 'Envolver'},
  ],
  'excecoes': [
    {'artista': 'Pregador', 'titulo': 'Fogo'},
  ],
  'decisoes': [
    {
      'artista': 'Annita',
      'titulo': 'Envolver',
      'motivo': 'musica',
      'usuario': 'fulano',
      'segundos_restantes': 82800,
    },
  ],
  'horas_decisao': 24,
  'ok': true,
};

OdApi _api(
  MockClient client, {
  String apiKey = 'od_dono',
}) =>
    OdApi(
      baseUrl: 'http://od.test:8000',
      apiKey: apiKey,
      client: client,
    );

void main() {
  group('leitura do acervo', () {
    test('GET /api/radio/musicas manda a busca e o limite', () async {
      Uri? vista;
      final api = _api(MockClient((request) async {
        vista = request.url;
        return _json(_acervo);
      }));

      final dados = await api.buscarCuradoria(termo: ' annita ');

      expect(vista?.path, '/api/radio/musicas');
      expect(vista?.queryParameters['q'], 'annita');
      expect(vista?.queryParameters['limite'], '200');
      expect(dados.musicas, hasLength(2));
      expect(dados.bloqueadas.single.nome, 'Annita — Envolver');
      expect(dados.excecoes.single.nome, 'Pregador — Fogo');
      expect(dados.decisoes.single.motivoLabel, 'música bloqueada');
      expect(dados.horasDecisao, 24);
    });

    test('busca vazia não manda q (o catálogo inteiro)', () async {
      Uri? vista;
      final api = _api(MockClient((request) async {
        vista = request.url;
        return _json(_acervo);
      }));

      await api.buscarCuradoria();

      expect(vista?.queryParameters.containsKey('q'), isFalse);
    });

    test('cada música diz por que sairia do ar', () async {
      final api = _api(MockClient((_) async => _json(_acervo)));

      final dados = await api.buscarCuradoria();

      expect(dados.musicas[0].selo, 'bloqueada');
      expect(dados.musicas[1].selo, 'cantor bloqueado');
      expect(dados.musicas[1].artistaBloqueado, isTrue);
    });

    test('403 vira mensagem de dono', () async {
      final api = _api(
        MockClient((_) async => _json({'ok': false, 'error': 'acesso_negado'}, 403)),
        apiKey: '',
      );

      expect(
        () => api.buscarCuradoria(),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'mensagem',
          contains('Só o dono'),
        )),
      );
    });
  });

  group('ações da curadoria', () {
    test('excluir manda caminho e bloquear=false por padrão', () async {
      Map<String, dynamic>? corpo;
      String? metodo;
      final api = _api(MockClient((request) async {
        metodo = request.method;
        corpo = jsonDecode(request.body) as Map<String, dynamic>;
        return _json(_acervo);
      }));

      final dados =
          await api.excluirMusicaDoAcervo('acervo/Outros/Annita - Envolver.mp3');

      expect(metodo, 'POST');
      expect(corpo?['caminho'], 'acervo/Outros/Annita - Envolver.mp3');
      expect(corpo?['bloquear'], isFalse);
      expect(dados.musicas, hasLength(2));
    });

    test('excluir e bloquear manda bloquear=true', () async {
      Map<String, dynamic>? corpo;
      final api = _api(MockClient((request) async {
        corpo = jsonDecode(request.body) as Map<String, dynamic>;
        return _json(_acervo);
      }));

      await api.excluirMusicaDoAcervo('x.mp3', bloquear: true);

      expect(corpo?['bloquear'], isTrue);
    });

    test('bloquear e desbloquear usam POST e DELETE no mesmo caminho', () async {
      final vistos = <String>[];
      final api = _api(MockClient((request) async {
        vistos.add('${request.method} ${request.url.path} '
            '${request.body}');
        return _json(_acervo);
      }));

      await api.bloquearMusica('Annita', 'Envolver');
      await api.desbloquearMusica('Annita', 'Envolver');

      expect(vistos[0], startsWith('POST /api/radio/musicas/bloqueadas'));
      expect(vistos[0], contains('"artista":"Annita"'));
      expect(vistos[1], startsWith('DELETE /api/radio/musicas/bloqueadas'));
    });

    test('exceções usam POST e DELETE em /excecoes', () async {
      final vistos = <String>[];
      final api = _api(MockClient((request) async {
        vistos.add('${request.method} ${request.url.path}');
        return _json(_acervo);
      }));

      await api.adicionarExcecao('Pregador', 'Fogo');
      await api.removerExcecao('Pregador', 'Fogo');

      expect(vistos, [
        'POST /api/radio/musicas/excecoes',
        'DELETE /api/radio/musicas/excecoes',
      ]);
    });

    test('faixa que não existe mais dá mensagem clara', () async {
      final api = _api(MockClient((_) async => _json({
            'ok': false,
            'motivo': 'musica_nao_encontrada',
          }, 404)));

      expect(
        () => api.excluirMusicaDoAcervo('sumiu.mp3'),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'mensagem',
          contains('não está mais no acervo'),
        )),
      );
    });

    test('item que já saiu da lista dá mensagem clara', () async {
      final api = _api(MockClient((_) async => _json({
            'ok': false,
            'error': 'nao_estava_na_lista',
          }, 404)));

      expect(
        () => api.desbloquearMusica('Annita', 'Envolver'),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'mensagem',
          contains('não está mais na lista'),
        )),
      );
    });
  });
}
