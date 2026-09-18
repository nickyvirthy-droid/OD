import 'package:flutter/material.dart';
import '../models/message.dart';
import '../services/od_api.dart';
import '../services/od_ws.dart';
import '../widgets/message_bubble.dart';

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

  static const _profiles = {
    'auto': {'name': 'Auto', 'icon': '🤖'},
    'guardian': {'name': 'Nicky Virthy', 'icon': '🐉'},
    'regulus': {'name': 'Conselheiro', 'icon': '⚖️'},
    'luma': {'name': 'Mentora', 'icon': '🌟'},
    'vox': {'name': 'Arauta', 'icon': '📜'},
    'athenae': {'name': 'Arquiteta', 'icon': '🏛️'},
    'nyx': {'name': 'Guardiã', 'icon': '🌙'},
    'nexus': {'name': 'Nexus', 'icon': '🔗'},
  };

  @override
  void initState() {
    super.initState();
    _chat = widget.chat ?? OdStreamingChat(widget.api);
  }

  @override
  void dispose() {
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

    final buffer = StringBuffer();

    try {
      await for (final delta in _chat.send(text, profile: _selectedProfile)) {
        if (!mounted) return;
        buffer.write(delta.text);
        setState(() {
          _lastTransport = delta.transport;
          if (_liveIndex == null) {
            _messages.add(
              OdMessage(role: 'assistant', content: buffer.toString()),
            );
            _liveIndex = _messages.length - 1;
          } else {
            _messages[_liveIndex!] = OdMessage(
              role: 'assistant',
              content: buffer.toString(),
            );
          }
        });
        _scrollToBottom();
      }
    } on OdStreamingError catch (e) {
      _showInterruption(e.message, buffer.toString());
    } catch (e) {
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

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Seletor de perfil
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
                    return MessageBubble(message: _messages[index]);
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
      child: ListView(
        scrollDirection: Axis.horizontal,
        children: _profiles.entries.map((entry) {
          final isSelected = _selectedProfile == entry.key;
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: ChoiceChip(
              label: Text('${entry.value['icon']} ${entry.value['name']}'),
              selected: isSelected,
              onSelected: (_) {
                setState(() => _selectedProfile = entry.key);
              },
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildWelcome() {
    return const Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text('🐉', style: TextStyle(fontSize: 64)),
          SizedBox(height: 16),
          Text(
            'OmegaDrakon',
            style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
          ),
          SizedBox(height: 8),
          Text(
            'Tecnologia que respira',
            style: TextStyle(fontSize: 16, color: Colors.grey),
          ),
          SizedBox(height: 24),
          Text(
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
      child: SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _buildTransportBadge(),
            Row(
              children: [
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
      ),
    );
  }
}
