import 'package:flutter/material.dart';
import '../models/message.dart';
import '../services/od_api.dart';
import '../widgets/message_bubble.dart';

/// Tela de conversa com o OmegaDrakon.
class ChatScreen extends StatefulWidget {
  final OdApi api;
  const ChatScreen({super.key, required this.api});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final List<OdMessage> _messages = [];
  bool _isLoading = false;
  String _selectedProfile = 'auto';

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
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _sendMessage() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isLoading) return;

    setState(() {
      _messages.add(OdMessage(role: 'user', content: text));
      _isLoading = true;
    });
    _controller.clear();
    _scrollToBottom();

    try {
      final response = await widget.api.sendMessage(
        text,
        profile: _selectedProfile,
      );
      setState(() {
        _messages.add(OdMessage(role: 'assistant', content: response));
      });
    } catch (e) {
      setState(() {
        _messages.add(OdMessage(
          role: 'assistant',
          content: '⚠️ Erro: ${e.toString()}',
        ));
      });
    } finally {
      setState(() => _isLoading = false);
      _scrollToBottom();
    }
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
                  itemCount: _messages.length + (_isLoading ? 1 : 0),
                  itemBuilder: (context, index) {
                    if (index == _messages.length) {
                      return const MessageBubble(
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
        child: Row(
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
      ),
    );
  }
}
