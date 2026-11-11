import 'package:flutter/material.dart';
import '../models/message.dart';
import '../services/od_api.dart';
import '../services/od_voice.dart';
import '../services/od_ws.dart';
import '../widgets/message_bubble.dart';

/// Quantas mensagens do histórico buscar ao abrir a conversa.
const int odHistoryLimit = 50;

/// Tela de conversa com o OmegaDrakon.
class ChatScreen extends StatefulWidget {
  final OdApi api;

  /// Chat com streaming (WebSocket) e fallback para `POST /message`.
  ///
  /// Injetável para os testes; em produção a tela cria o padrão, que deriva a
  /// porta do streaming (8001) da URL do servidor já configurada.
  final OdStreamingChat? chat;

  const ChatScreen({super.key, required this.api, this.chat});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final List<OdMessage> _messages = [];
  bool _isLoading = false;
  String _selectedProfile = 'auto';

  /// Chat de streaming — mantido entre mensagens de propósito: a instância
  /// guarda o cooldown do WebSocket, e recriá-la a cada envio faria o app
  /// tentar a porta fechada toda vez, pagando o timeout antes do fallback.
  late final OdStreamingChat _chat;

  /// Índice da bolha que está sendo preenchida token-a-token (null = não há
  /// streaming em curso).
  int? _liveIndex;

  /// De onde veio a última resposta (selo discreto acima do campo de texto).
  OdChatTransport? _lastTransport;

  /// Aprovação aguardando o "sim"/"não" do dono (frame `human_loop_pending`).
  /// Enquanto não for respondida, o turno segue pausado no servidor.
  OdHumanApproval? _pendingApproval;

  /// Voz (v1.17.3): estado do microfone — o botão alterna gravar/parar e
  /// mostra progresso enquanto o servidor transcreve.
  OdVoiceState _voiceState = OdVoiceState.idle;
  bool _speakOn = false;
  late final OdVoice _voice;

  static const _voiceTag = 'voz';

  // Nomes CANÔNICOS da Plêiade (cânone Personagens.md) — o chip mostra
  // QUEM vai responder (Regulus), não só o cargo (Conselheiro).
  static const _profiles = {
    'auto': {'name': 'Auto', 'icon': '🤖'},
    'guardian': {'name': 'Nicky Virthy', 'icon': '🐉'},
    'regulus': {'name': 'Regulus', 'icon': '⚖️'},
    'luma': {'name': 'Luma', 'icon': '🌟'},
    'vox': {'name': 'Vox', 'icon': '📜'},
    'athenae': {'name': 'Athenae', 'icon': '🏛️'},
    'nyx': {'name': 'Nyx', 'icon': '🌙'},
    'nexus': {'name': 'Nexus', 'icon': '🔗'},
  };

  @override
  void initState() {
    super.initState();
    _chat = widget.chat ?? OdStreamingChat(widget.api);
    _voice = OdVoice();
    _loadHistory();
  }

  /// Ciclo do microfone: 1º toque grava, 2º para e manda transcrever;
  /// o texto reconhecido entra no campo (o usuário revisa antes de enviar).
  Future<void> _toggleMic() async {
    if (_voiceState == OdVoiceState.recording) {
      await _voice.stopRecording();
      return;
    }
    if (_voiceState != OdVoiceState.idle) return;
    setState(() => _voiceState = OdVoiceState.recording);
    try {
      final audio = await _voice.record();
      setState(() => _voiceState = OdVoiceState.transcribing);
      final text = await widget.api.transcribe(audio);
      if (mounted) {
        setState(() {
          _controller.text = _controller.text.isEmpty
              ? text
              : '${_controller.text.trim()} $text';
        });
      }
    } on OdVoiceError catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(OdMessage(role: 'assistant', content: '🎙 ${e.message}'));
        });
        _scrollToBottom();
      }
    } on OdApiError catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(
            OdMessage(
              role: 'assistant',
              content: '🎙 ${e.message}',
              route: _voiceTag,
            ),
          );
        });
        _scrollToBottom();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _messages.add(
            OdMessage(role: 'assistant', content: '🎙 Falha na voz: $e'),
          );
        });
        _scrollToBottom();
      }
    } finally {
      if (mounted) setState(() => _voiceState = OdVoiceState.idle);
    }
  }

  /// Resposta por voz: sintetiza a ÚLTIMA bolha do assistente e toca.
  /// Best-effort — falha de voz nunca remove/altera o texto na tela.
  Future<void> _speakLast() async {
    if (!_speakOn) {
      setState(() => _speakOn = true);
    }
    final last = _messages.lastWhere(
      (m) => m.role == 'assistant' && !m.content.startsWith('⚠️') && !m.content.startsWith('🎙'),
      orElse: () => OdMessage(role: 'assistant', content: ''),
    );
    if (last.content.isEmpty) return;
    try {
      final wav = await widget.api.synthesize(last.content);
      await _voice.play(wav);
    } catch (_) {
      // Voz é opcional.
    }
  }

  /// Busca as mensagens salvas da conta (GET /history/{user_id}) para a
  /// conversa continuar de onde parou — mesmo balde do chat web e do Telegram.
  /// Best-effort: falha de rede/404/501 só deixa a lista como está.
  Future<void> _loadHistory() async {
    try {
      final history = await widget.api.getHistory(limit: odHistoryLimit);
      if (!mounted || history.isEmpty || _messages.isNotEmpty) return;
      setState(() {
        _messages.addAll(
          history.map(
            (m) => OdMessage(
              role: m.isUser ? 'user' : 'assistant',
              content: m.content,
              timestamp: m.timestamp,
              answeredBy: m.answeredBy,
              serverId: m.serverId,
            ),
          ),
        );
      });
      _scrollToBottom();
    } catch (_) {
      // Sem histórico visual não trava o chat.
    }
  }

  @override
  void dispose() {
    _voice.dispose();
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  /// Envia a mensagem e mostra a resposta conforme ela chega.
  ///
  /// O transporte é escolhido pelo [OdStreamingChat]: WebSocket quando o core
  /// aceita (resposta token-a-token) e `POST /message` como fallback. A bolha
  /// do assistente nasce no primeiro pedaço recebido e é reescrita a cada
  /// token — até lá a lista mostra "Digitando...".
  Future<void> _sendMessage() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isLoading) return;

    setState(() {
      _messages.add(OdMessage(role: 'user', content: text));
      _isLoading = true;
      _liveIndex = null;
    });
    _controller.clear();
    _scrollToBottom();

    await _consume(_chat.send(text, profile: _selectedProfile));
  }

  /// Responde ao pedido de aprovação pendente: manda o frame `decision` pelo
  /// WebSocket (`sim`/`nao`) e mostra o resultado do turno retomado.
  ///
  /// O card SOME enquanto a decisão está a caminho; se ela falhar, ele volta
  /// para o dono poder tentar de novo (o aviso de erro manda conferir antes).
  Future<void> _decidir(bool aprovar) async {
    final aprovacao = _pendingApproval;
    if (aprovacao == null || _isLoading) return;

    setState(() {
      _isLoading = true;
      _liveIndex = null;
      _pendingApproval = null;
    });
    _scrollToBottom();

    await _consume(
      _chat.decide(aprovacao, aprovar: aprovar),
      restore: aprovacao,
    );
  }

  /// Consome um stream do chat (mensagem nova ou decisão de aprovação),
  /// preenchendo a bolha do assistente token-a-token.
  ///
  /// [restore] devolve o card de aprovação à tela quando a decisão não pôde ser
  /// entregue. O frame `human_loop_pending` NÃO cria bolha: o pedido aparece no
  /// card do rodapé (com os botões), não como resposta vazia.
  Future<void> _consume(
    Stream<OdChatDelta> stream, {
    OdHumanApproval? restore,
  }) async {
    final buffer = StringBuffer();
    // Quem/resposta do frame `done` (profile_name/llm_used/route). O streaming
    // só mostra o TEXTO; os metadados chegam no final.
    var answeredBy = '';
    var route = '';

    try {
      await for (final delta in stream) {
        if (!mounted) return;
        _lastTransport = delta.transport;
        final aprovacao = delta.approval;
        if (aprovacao != null) {
          setState(() => _pendingApproval = aprovacao);
          continue;
        }
        buffer.write(delta.text);
        if (delta.answeredBy.isNotEmpty) answeredBy = delta.answeredBy;
        if (delta.route.isNotEmpty) route = delta.route;
        // Sem token nenhum (decisão retomada), o texto vem inteiro no `done`.
        final texto = buffer.isEmpty ? delta.finalText : buffer.toString();
        setState(() {
          if (_liveIndex == null) {
            _messages.add(
              OdMessage(
                role: 'assistant',
                content: texto,
                answeredBy: answeredBy,
                route: route,
              ),
            );
            _liveIndex = _messages.length - 1;
          } else {
            _messages[_liveIndex!] = OdMessage(
              role: 'assistant',
              content: texto,
              answeredBy: answeredBy,
              route: route,
            );
          }
        });
        _scrollToBottom();
      }
    } on OdStreamingError catch (e) {
      _showInterruption(e.message, buffer.toString());
    } catch (e) {
      if (restore != null) {
        setState(() => _pendingApproval = restore);
      }
      setState(() {
        _messages.add(OdMessage(
          role: 'assistant',
          content: '⚠️ Erro: ${e.toString()}',
        ));
      });
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
        _scrollToBottom();
      }
    }
  }

  /// Resposta cortada no meio do streaming: mantém o que chegou e avisa na
  /// MESMA bolha (uma bolha nova de erro pareceria uma segunda resposta).
  void _showInterruption(String notice, String partial) {
    if (!mounted) return;
    setState(() {
      final aviso = '⚠️ $notice';
      final index = _liveIndex;
      if (index == null) {
        _messages.add(OdMessage(role: 'assistant', content: aviso));
      } else {
        _messages[index] = OdMessage(
          role: 'assistant',
          content: '$partial\n\n$aviso',
        );
      }
    });
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  /// Apaga UMA mensagem do histórico do usuário (long press na bolha do usuário).
  ///
  /// O id vem do [OdMessage.serverId] quando a mensagem veio do histórico.
  /// Mensagens escritas AINDA NÃO têm id no app (streaming/POST /message não
  /// devolvem) — nesse caso o id é resolvido no servidor pelo conteúdo
  /// ([OdApi.resolveUserMessageId]) para o apagar valer também para o que
  /// acabou de ser escrito. Sem candidata no servidor, só remove da tela
  /// (mensagem sincronizada depois reapareceria — o aviso diz isso).
  Future<void> _confirmDeleteMessage(int index) async {
    final message = _messages[index];
    if (!message.isUser) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Apagar esta mensagem?'),
        content: Text(
          message.content.length > 100
              ? '${message.content.substring(0, 100)}…'
              : message.content,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Apagar'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    // Mensagem recém-escrita: acha o id dela no servidor antes de apagar.
    var serverId = message.serverId;
    if (serverId == null) {
      try {
        serverId = await widget.api.resolveUserMessageId(message.content);
      } catch (_) {
        serverId = null; // sem rede/histório: cai no caminho local honesto
      }
      if (!mounted) return;
    }

    if (serverId != null) {
      try {
        await widget.api.deleteHistoryMessage(serverId);
        if (!mounted) return;
        setState(() => _messages.removeAt(index));
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Mensagem apagada no servidor')),
        );
      } on OdAuthError {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Sessão inválida — faça login novamente')),
        );
      } on OdApiError catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Falha ao apagar no servidor: ${e.message}')),
        );
      }
    } else {
      // Sem id no servidor — só remove da UI (com aviso honesto).
      setState(() => _messages.removeAt(index));
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Mensagem removida da conversa local')),
      );
    }
  }

  /// Apaga TODA a conversa da conta no servidor (DELETE /history/me).
  Future<void> _confirmClearHistory() async {
    if (!widget.api.hasCredential) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('É preciso estar logado para limpar o histórico')),
      );
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Apagar TODA a conversa?'),
        content: const Text(
          'Isso remove todas as mensagens salvas desta conta no servidor. '
          'A ação não tem volta.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Apagar tudo'),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    try {
      final removed = await widget.api.clearHistory();
      if (!mounted) return;
      setState(() => _messages.clear());
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Conversa apagada ($removed mensagens removidas do servidor)')),
      );
    } on OdAuthError {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Sessão inválida — faça login novamente')),
      );
    } on OdApiError catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Falha ao limpar: ${e.message}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Seletor de perfil + menu de ações
        _buildProfileSelector(),
        // Lista de mensagens
        Expanded(
          child: _messages.isEmpty
              ? _buildWelcome()
              : ListView.builder(
                  controller: _scrollController,
                  padding: const EdgeInsets.all(16),
                  // "Digitando..." só enquanto NADA chegou: com o streaming, a
                  // bolha do assistente já aparece com o primeiro token.
                  itemCount: _messages.length +
                      (_isLoading && _liveIndex == null ? 1 : 0),
                  itemBuilder: (context, index) {
                    if (index == _messages.length) {
                      return MessageBubble(
                        message: OdMessage(
                          role: 'assistant',
                          content: 'Digitando...',
                        ),
                      );
                    }
                    final message = _messages[index];
                    // Só mensagens do usuário podem ser apagadas individualmente
                    final canDelete = message.isUser;
                    return MessageBubble(
                      message: message,
                      canDelete: canDelete,
                      onLongPress: canDelete ? () => _confirmDeleteMessage(index) : null,
                    );
                  },
                ),
        ),
        // Campo de entrada
        _buildInput(),
      ],
    );
  }

  Widget _buildProfileSelector() {
    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Row(
        children: [
          Expanded(
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: _profiles.entries.map((entry) {
                final isSelected = _selectedProfile == entry.key;
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  child: ChoiceChip(
                    label: entry.key == 'guardian'
                        ? Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Image.asset('assets/logo.png', width: 14, height: 14),
                              const SizedBox(width: 4),
                              Text(entry.value['name'] ?? ''),
                            ],
                          )
                        : Text('${entry.value['icon']} ${entry.value['name']}'),
                    selected: isSelected,
                    onSelected: (_) {
                      setState(() => _selectedProfile = entry.key);
                    },
                  ),
                );
              }).toList(),
            ),
          ),
          // Menu de ações (limpar conversa, etc.)
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert),
            tooltip: 'Opções da conversa',
            onSelected: (value) {
              if (value == 'clear_history') _confirmClearHistory();
            },
            itemBuilder: (context) => [
              const PopupMenuItem<String>(
                value: 'clear_history',
                child: Row(
                  children: [
                    Icon(Icons.delete_sweep, size: 20),
                    SizedBox(width: 8),
                    Text('Limpar conversa'),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildWelcome() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Image.asset('assets/logo.png', width: 96, height: 96),
          const SizedBox(height: 16),
          const Text(
            'OmegaDrakon',
            style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          const Text(
            'Tecnologia que respira',
            style: TextStyle(fontSize: 16, color: Colors.grey),
          ),
          const SizedBox(height: 24),
          const Text(
            'Envie uma mensagem para começar',
            style: TextStyle(color: Colors.grey),
          ),
        ],
      ),
    );
  }

  /// Selo discreto do transporte da última resposta — é o que permite ver no
  /// celular se o streaming (⚡) está ativo ou se o app caiu para o REST (↔).
  Widget _buildTransportBadge() {
    final transporte = _lastTransport;
    if (transporte == null) return const SizedBox.shrink();
    final streaming = transporte == OdChatTransport.webSocket;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(
          streaming ? Icons.bolt : Icons.swap_horiz,
          size: 14,
          color: Colors.grey,
        ),
        const SizedBox(width: 4),
        Text(
          streaming ? 'Streaming ativo' : 'Resposta via REST',
          style: const TextStyle(fontSize: 11, color: Colors.grey),
        ),
      ],
    );
  }

  /// Card de aprovação (human-in-the-loop): o turno pausou esperando o
  /// "sim"/"não" do dono, e a resposta sai pelo frame `decision` do WebSocket.
  Widget _buildApprovalCard() {
    final aprovacao = _pendingApproval;
    if (aprovacao == null) return const SizedBox.shrink();
    final colorScheme = Theme.of(context).colorScheme;
    final detalhes = aprovacao.detalhes.isNotEmpty
        ? aprovacao.detalhes
        : (aprovacao.acao.isNotEmpty
            ? 'executar ${aprovacao.acao}'
            : 'executar uma ação externa');

    return Container(
      key: const ValueKey('od-aprovacao-pendente'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 4),
      decoration: BoxDecoration(
        color: colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colorScheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.verified_user_outlined,
                  size: 18, color: colorScheme.primary),
              const SizedBox(width: 6),
              const Text(
                'Aprovação necessária',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'O OD quer $detalhes. Nada foi executado ainda — responda para '
            'liberar ou cancelar.',
            style: const TextStyle(fontSize: 13),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: _isLoading ? null : () => _decidir(false),
                style: TextButton.styleFrom(foregroundColor: Colors.red),
                child: const Text('Não'),
              ),
              const SizedBox(width: 4),
              FilledButton(
                onPressed: _isLoading ? null : () => _decidir(true),
                child: const Text('Sim'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildInput() {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.05),
            blurRadius: 10,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _buildApprovalCard(),
          _buildTransportBadge(),
          Row(
            children: [
              // Voz (v1.17.3): gravar → transcrever → texto no campo.
              IconButton(
                onPressed: _isLoading ? null : _toggleMic,
                tooltip: 'Falar com o OmegaDrakon',
                icon: _voiceState == OdVoiceState.recording
                    ? const Icon(Icons.stop_circle, color: Colors.red)
                    : _voiceState == OdVoiceState.transcribing
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.mic),
              ),
              Expanded(
                child: TextField(
                  controller: _controller,
                  decoration: const InputDecoration(
                    hintText: 'Digite sua mensagem...',
                    border: OutlineInputBorder(),
                    contentPadding:
                        EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  ),
                  onSubmitted: (_) => _sendMessage(),
                  textInputAction: TextInputAction.send,
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                onPressed: _speakLast,
                tooltip: 'Ouvir a última resposta',
                icon: Icon(
                  _speakOn ? Icons.volume_up : Icons.volume_off,
                  color: _speakOn ? Theme.of(context).colorScheme.primary : null,
                ),
              ),
              IconButton.filled(
                onPressed: _isLoading ? null : _sendMessage,
                icon: _isLoading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.send),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
