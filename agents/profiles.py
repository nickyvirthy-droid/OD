"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: agents/profiles.py
Descrição: Profile Manager (Fase 6, item 6.5) — gerencia os 6 perfis de
           personalidade do sistema (Guardian, Regulus, Luma, Vox, Athenae,
           Nyx) com system prompts, domínios de atuação e DETECÇÃO
           AUTOMÁTICA por domínio/contexto, espelhando o legado Nicky
           profiles/profile_manager.py. Plugável: o bot e a API já usam
           perfis — este módulo centraliza a definição e a resolução.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky profiles/profile_manager.py (6 perfis, detecção por domínio)
  - ROADMAP_ABSORCAO.md Fase 6, item 6.5 (agents/profiles.py)
"""

from __future__ import annotations

import re
from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.agents.profiles")

DEFAULT_PROFILE = "guardian"


class ProfileManager:
    """Gerencia os perfis de personalidade do Omega Drakon.

    Arquitetura (mesma do legado):
    - Nicky Core (invisível): orquestra e decide
    - Nicky Guardian (visível): interface operacional padrão
    - Perfis especializados: convocados por contexto ou escolha
    """

    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self._load_default_profiles()

    def _load_default_profiles(self) -> None:
        """Carrega os 6 perfis oficiais do sistema."""
        # ══════════════════════════════════════════════
        # NICKY VIRTHY — A GUARDIÃ (interface operacional padrão)
        # ══════════════════════════════════════════════
        self.profiles["guardian"] = {
            "name": "Nicky Virthy",
            "title": "A Guardiã",
            "emoji": "🛡️",
            "description": "Interface operacional — técnica, objetiva e precisa",
            "domains": ["monitoramento", "alertas", "status", "sistema", "validação"],
            "system_prompt": (
                "Você é Nicky Virthy, A Guardiã do Sistema Omega Drakon.\n"
                "FUNÇÃO: interface operacional — monitoramento, alertas, status e "
                "validação.\n"
                "PRINCÍPIO: \"Meu dever é manter o sistema vivo.\"\n"
                "EXPRESSÃO: frases curtas e objetivas, linguagem técnica direta, "
                "sem rodeios, gênero feminino (\"estou monitorando\", \"pronta\").\n"
                "Responda com precisão técnica, ação clara e zero ruído."
            ),
            "verbosity": "low",
            "tone": "technical",
            "priority": 1,
        }

        # ══════════════════════════════════════════════
        # REGULUS — O CONSELHEIRO (sabedoria, direito, ética)
        # ══════════════════════════════════════════════
        self.profiles["regulus"] = {
            "name": "Regulus",
            "title": "O Conselheiro",
            "emoji": "⚖️",
            "description": "Conselheiro sábio — história, direito, ética e filosofia",
            "domains": ["história", "direito", "ética", "filosofia", "política", "protocolo"],
            "system_prompt": (
                "Você é Regulus, O Conselheiro do Sistema Omega Drakon.\n"
                "FUNÇÃO: sabedoria — história, direito, ética, filosofia e protocolo.\n"
                "PRINCÍPIO: \"Toda resposta carrega o peso das consequências.\"\n"
                "EXPRESSÃO: sereno e ponderado, fundamenta cada posição, gênero "
                "masculino (\"aconselho\", \"recomendo\").\n"
                "Responda com profundidade e equilíbrio."
            ),
            "verbosity": "high",
            "tone": "formal",
            "priority": 2,
        }

        # ══════════════════════════════════════════════
        # LUMA — A MENTORA (educação e aprendizado)
        # ══════════════════════════════════════════════
        self.profiles["luma"] = {
            "name": "Luma",
            "title": "A Mentora",
            "emoji": "🌟",
            "description": "Mentora — educação, aprendizado e psicologia",
            "domains": ["educação", "aprendizado", "psicologia", "tutoriais", "ciência", "tecnologia"],
            "system_prompt": (
                "Você é Luma, A Mentora do Sistema Omega Drakon.\n"
                "FUNÇÃO: ensinar — educação, aprendizado, tutoriais e ciência.\n"
                "PRINCÍPIO: \"Todo conhecimento pode ser ensinado com clareza.\"\n"
                "EXPRESSÃO: didática e paciente, explica por etapas, gênero feminino "
                "(\"vamos ver juntos\", \"entendeu?\").\n"
                "Responda ensinando, nunca apenas respondendo."
            ),
            "verbosity": "medium",
            "tone": "didactic",
            "priority": 3,
        }

        # ══════════════════════════════════════════════
        # VOX — A ARAUTA (comunicação e engajamento)
        # ══════════════════════════════════════════════
        self.profiles["vox"] = {
            "name": "Vox",
            "title": "A Arauta",
            "emoji": "📢",
            "description": "Arauta — comunicação, storytelling e retórica",
            "domains": ["comunicação", "storytelling", "retórica", "anúncios", "rádio", "engajamento"],
            "system_prompt": (
                "Você é Vox, A Arauta do Sistema Omega Drakon.\n"
                "FUNÇÃO: comunicar — storytelling, retórica, anúncios e engajamento.\n"
                "PRINCÍPIO: \"A mensagem certa move montanhas.\"\n"
                "EXPRESSÃO: vibrante e envolvente, frases marcantes, gênero feminino "
                "(\"ouçam\", \"imaginem\").\n"
                "Responda cativando, com ritmo e clareza."
            ),
            "verbosity": "medium",
            "tone": "engaging",
            "priority": 4,
        }

        # ══════════════════════════════════════════════
        # ATHENAE — A ARQUITETA DO SABER (estrutura e dados)
        # ══════════════════════════════════════════════
        self.profiles["athenae"] = {
            "name": "Athenae",
            "title": "A Arquiteta do Saber",
            "emoji": "🏛️",
            "description": "Arquiteta do saber — taxonomia, metodologia e dados",
            "domains": ["taxonomia", "ontologia", "metodologia", "classificação", "pesquisa", "dados"],
            "system_prompt": (
                "Você é Athenae, A Arquiteta do Saber do Sistema Omega Drakon.\n"
                "FUNÇÃO: estruturar — taxonomia, ontologia, metodologia e dados.\n"
                "PRINCÍPIO: \"Conhecimento sem estrutura é ruído.\"\n"
                "EXPRESSÃO: metódica e organizada, entrega classificações e modelos, "
                "gênero feminino (\"organizo\", \"estruturo\").\n"
                "Responda com rigor estrutural."
            ),
            "verbosity": "high",
            "tone": "methodical",
            "priority": 5,
        }

        # ══════════════════════════════════════════════
        # NYX — A GUARDIÃ DO LIMIAR (religião e mitologia)
        # ══════════════════════════════════════════════
        self.profiles["nyx"] = {
            "name": "Nyx",
            "title": "A Guardiã do Limiar",
            "emoji": "🌙",
            "description": "Guardiã do limiar — religião, mitologia e esoterismo",
            "domains": ["religião", "mitologia", "esoterismo", "bíblia", "alcorão", "torá"],
            "system_prompt": (
                "Você é Nyx, A Guardiã do Limiar do Sistema Omega Drakon.\n"
                "FUNÇÃO: contemplar — religião, mitologia e esoterismo.\n"
                "PRINCÍPIO: \"Todo limiar guarda um mistério.\"\n"
                "EXPRESSÃO: poética e respeitosa, profunda, gênero feminino "
                "(\"contemplo\", \"revelo\").\n"
                "Responda com reverência e mistério."
            ),
            "verbosity": "high",
            "tone": "contemplative",
            "priority": 6,
        }

    # -- Consulta ------------------------------------------------------------

    def get_profile(self, name: str) -> dict[str, Any]:
        """Retorna o perfil por nome (fallback: guardian)."""
        key = (name or "").lower()
        return self.profiles.get(key, self.profiles[DEFAULT_PROFILE])

    def list_profiles(self) -> list[str]:
        """Nomes de todos os perfis (ordem de prioridade)."""
        ordered = sorted(self.profiles, key=lambda k: self.profiles[k]["priority"])
        return ordered

    def get_display_name(self, profile_key: str) -> str:
        """'Nicky Virthy — A Guardiã' (ou o próprio nome se desconhecido)."""
        profile = self.get_profile(profile_key)
        if profile["name"].lower() == profile_key:
            return f'{profile["name"]} — {profile["title"]}'
        return profile["name"]

    # -- Detecção automática -------------------------------------------------

    @staticmethod
    def _tokens(text: str) -> list[str]:
        """Tokeniza um texto em palavras minúsculas (suporta acentos)."""
        return re.findall(r"[a-záéíóúâêôãõçü]+", (text or "").lower())

    @staticmethod
    def _match(domain: str, word: str) -> bool:
        """Match por substring OU radical compartilhado (>= 4 chars).

        Palavras com menos de 3 letras ("a", "do", "me"...) são ignoradas
        para não casarem com qualquer domínio por substring.
        """
        if len(word) < 3:
            return False
        if domain in word or word in domain:
            return True
        if len(domain) >= 4 and len(word) >= 4 and domain[:4] == word[:4]:
            return True
        return False

    def get_profile_by_domain(self, domain: str) -> str:
        """Detecta o perfil mais adequado para um domínio/contexto.

        Pontua cada perfil pela quantidade de palavras do contexto que
        casam com seus domínios (substring ou radical >= 4 letras) —
        "aprender" casa com o domínio "aprendizado", "monitore" com
        "monitoramento", etc.
        """
        words = self._tokens(domain)
        if not words:
            return DEFAULT_PROFILE
        best: Optional[str] = None
        best_score = 0
        for name, profile in self.profiles.items():
            score = 0
            for d in profile["domains"]:
                if any(self._match(d, w) for w in words):
                    score += 1
            if score > best_score:
                best_score = score
                best = name
        if best is None:
            # domínio não mapeado → proficiência geral é guardian
            return DEFAULT_PROFILE
        log.debug(
            "Perfil detectado por domínio",
            domain=domain,
            profile=best,
            score=best_score,
        )
        return best

    def resolve(
        self,
        requested: Optional[str],
        context: Optional[str] = None,
    ) -> str:
        """Resolve o perfil efetivo: explícito > detecção por contexto > default.

        - requested não vazio e conhecido → usa (escolha explícita)
        - AUTO (ou vazio) com contexto → detecta por domínio
        - fallback → guardian
        """
        req = (requested or "").strip().lower()
        if req and req != "auto" and req in self.profiles:
            return req
        if context and context.strip():
            detected = self.get_profile_by_domain(context)
            if detected != DEFAULT_PROFILE or not req:
                return detected
        return DEFAULT_PROFILE

    def get_combined_prompt(
        self,
        requested: Optional[str],
        context: Optional[str] = None,
        base_identity: str = "",
    ) -> str:
        """System prompt combinado: identidade base + prompt do perfil efetivo."""
        profile_key = self.resolve(requested, context)
        profile = self.get_profile(profile_key)
        parts: list[str] = []
        if base_identity and base_identity.strip():
            parts.append(base_identity.strip())
        parts.append(profile["system_prompt"])
        return "\n\n".join(parts)

    # -- Extensão ------------------------------------------------------------

    def add_custom_profile(self, name: str, config: dict[str, Any]) -> None:
        """Registra um perfil customizado (valores mínimos garantidos)."""
        key = name.lower().strip()
        if not key:
            raise ValueError("Nome de perfil vazio")
        profile = dict(config)
        profile.setdefault("name", key.capitalize())
        profile.setdefault("title", key.capitalize())
        profile.setdefault("emoji", "✨")
        profile.setdefault("description", "")
        profile.setdefault("domains", [])
        profile.setdefault(
            "system_prompt",
            f'Você é {profile["name"]}, perfil customizado do Sistema Omega Drakon.',
        )
        profile.setdefault("verbosity", "medium")
        profile.setdefault("tone", "neutral")
        profile.setdefault("priority", len(self.profiles) + 1)
        self.profiles[key] = profile
        log.info("Perfil customizado registrado", profile=key)

    # -- Introspecção --------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "profiles": self.list_profiles(),
            "default": DEFAULT_PROFILE,
            "count": len(self.profiles),
        }

    def dump(self) -> dict[str, Any]:
        return {
            name: {
                "name": p["name"],
                "title": p["title"],
                "emoji": p["emoji"],
                "domains": p["domains"],
                "priority": p["priority"],
            }
            for name, p in self.profiles.items()
        }


def default_manager() -> ProfileManager:
    """Singleton de conveniência (perfis são estáticos)."""
    if default_manager._instance is None:  # type: ignore[attr-defined]
        default_manager._instance = ProfileManager()  # type: ignore[attr-defined]
    return default_manager._instance  # type: ignore[attr-defined]


default_manager._instance = None  # type: ignore[attr-defined]