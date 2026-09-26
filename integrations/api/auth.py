"""
OMEGA DRAKON • API AUTH
Módulo de autenticação de usuários para a API REST e o chat web.

Camadas:
  - UserStore: registro, login, sessões, API keys (persistência via Database)
  - Hash de senhas: PBKDF2-SHA256 com salt aleatório (stdlib, sem bcrypt)
  - Tokens de sessão: UUID4, expiração configurável, armazenados no banco

Uso típico:
    store = UserStore(database)
    user = store.register("alex", "alex@example.com", "senha123")
    token = store.login("alex", "senha123")
    user = store.validate_session(token)
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from core.logger import get_logger
from storage.database import Database

__signature__ = "OD // CORE"

log = get_logger("omega.auth")

# ---------------------------------------------------------------------------
# Hash de senhas (PBKDF2-SHA256, sem dependências externas)
# ---------------------------------------------------------------------------

_HASH_ITERATIONS = 260_000  # OWASP 2023 recommendation for PBKDF2-SHA256
_HASH_SALT_BYTES = 32
_HASH_KEY_LENGTH = 32


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """Hash de senha com PBKDF2-SHA256. Retorna 'salt_hex:hash_hex'."""
    if salt is None:
        salt = os.urandom(_HASH_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _HASH_ITERATIONS,
        dklen=_HASH_KEY_LENGTH,
    )
    return f"{salt.hex()}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Verifica senha contra o hash armazenado."""
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            _HASH_ITERATIONS,
            dklen=_HASH_KEY_LENGTH,
        )
        return secrets.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def _generate_api_key() -> str:
    """Gera uma API key aleatória (formato: od_ + 40 chars hex)."""
    return "od_" + secrets.token_hex(20)


def _generate_session_token() -> str:
    """Gera um token de sessão UUID4."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# UserStore
# ---------------------------------------------------------------------------

@dataclass
class User:
    """Usuário autenticado."""
    id: int
    username: str
    email: str
    api_key: str
    created_at: float


class AuthError(Exception):
    """Erro de autenticação."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


class UserStore:
    """Gerenciamento de usuários, sessões e API keys.

    Tabelas:
      - users: id, username, email, password_hash, api_key, created_at
      - sessions: token, user_id, created_at, expires_at
    """

    SCHEMA_USERS = {
        "id": "INTEGER PRIMARY KEY",
        "username": "TEXT UNIQUE NOT NULL",
        "email": "TEXT UNIQUE NOT NULL",
        "password_hash": "TEXT NOT NULL",
        "api_key": "TEXT UNIQUE NOT NULL",
        "created_at": "REAL NOT NULL",
    }

    SCHEMA_SESSIONS = {
        "token": "TEXT PRIMARY KEY",
        "user_id": "INTEGER NOT NULL",
        "created_at": "REAL NOT NULL",
        "expires_at": "REAL NOT NULL",
    }

    # Vínculo de um chat do Telegram a uma conta (comando /entrar). O balde do
    # Telegram é o id numérico do chat; vinculado, a conversa cai na conta.
    SCHEMA_TELEGRAM_LINKS = {
        "chat_id": "TEXT PRIMARY KEY",
        "username": "TEXT NOT NULL",
        "linked_at": "REAL NOT NULL",
    }

    def __init__(
        self,
        db: Database,
        *,
        session_ttl_s: float = 7 * 24 * 3600,  # 7 dias
    ) -> None:
        self._db = db
        self._session_ttl = session_ttl_s
        # Cria tabelas se não existirem
        db.create_table("users", self.SCHEMA_USERS)
        db.create_table("sessions", self.SCHEMA_SESSIONS)
        db.create_table("telegram_links", self.SCHEMA_TELEGRAM_LINKS)

    # -- Registro -------------------------------------------------------------

    def register(self, username: str, email: str, password: str) -> User:
        """Registra um novo usuário. Lança AuthError se username/email já existe."""
        username = username.strip().lower()
        email = email.strip().lower()

        if len(username) < 3:
            raise AuthError("Username deve ter pelo menos 3 caracteres", 400)
        if len(password) < 6:
            raise AuthError("Senha deve ter pelo menos 6 caracteres", 400)
        if "@" not in email:
            raise AuthError("Email inválido", 400)

        # Verifica duplicatas
        existing = self._db.query(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (username, email),
            limit=1,
        )
        if existing:
            raise AuthError("Username ou email já cadastrado", 409)

        now = time.time()
        password_hash = _hash_password(password)
        api_key = _generate_api_key()

        user_id = self._db.repository("users").insert({
            "username": username,
            "email": email,
            "password_hash": password_hash,
            "api_key": api_key,
            "created_at": now,
        })

        log.info("Usuário registrado", username=username, user_id=user_id)
        return User(
            id=user_id,
            username=username,
            email=email,
            api_key=api_key,
            created_at=now,
        )

    # -- Login ----------------------------------------------------------------

    def login(self, username: str, password: str) -> str:
        """Autentica usuário e retorna um token de sessão."""
        username = username.strip().lower()

        rows = self._db.query(
            "SELECT id, username, email, password_hash, api_key, created_at "
            "FROM users WHERE username = ?",
            (username,),
            limit=1,
        )
        if not rows:
            raise AuthError("Usuário ou senha inválidos", 401)

        row = rows[0]
        if not _verify_password(password, row["password_hash"]):
            raise AuthError("Usuário ou senha inválidos", 401)

        token = self._create_session(row["id"])
        log.info("Login realizado", username=username, user_id=row["id"])
        return token

    def login_with_api_key(self, api_key: str) -> Optional[User]:
        """Autentica por API key (para o app mobile e curl)."""
        rows = self._db.query(
            "SELECT id, username, email, api_key, created_at "
            "FROM users WHERE api_key = ?",
            (api_key,),
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            api_key=row["api_key"],
            created_at=row["created_at"],
        )

    # -- Sessões --------------------------------------------------------------

    def _create_session(self, user_id: int) -> str:
        """Cria uma sessão e retorna o token."""
        token = _generate_session_token()
        now = time.time()
        expires = now + self._session_ttl

        self._db.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token, user_id, now, expires),
        )
        return token

    def validate_session(self, token: str) -> Optional[User]:
        """Valida um token de sessão. Retorna o User ou None."""
        rows = self._db.query(
            "SELECT s.token, s.user_id, s.expires_at, "
            "u.id, u.username, u.email, u.api_key, u.created_at "
            "FROM sessions s JOIN users u ON s.user_id = u.id "
            "WHERE s.token = ?",
            (token,),
            limit=1,
        )
        if not rows:
            return None

        row = rows[0]
        if row["expires_at"] < time.time():
            # Sessão expirada — limpa
            self._db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None

        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            api_key=row["api_key"],
            created_at=row["created_at"],
        )

    def logout(self, token: str) -> None:
        """Remove uma sessão (logout)."""
        self._db.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def logout_all(self, user_id: int) -> int:
        """Remove todas as sessões de um usuário. Retorna quantas removeu."""
        return self._db.execute(
            "DELETE FROM sessions WHERE user_id = ?", (user_id,)
        )

    # -- Limpeza --------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Remove sessões expiradas. Retorna quantas removeu."""
        now = time.time()
        return self._db.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (now,)
        )

    # -- Consulta -------------------------------------------------------------

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Busca usuário por ID."""
        rows = self._db.query(
            "SELECT id, username, email, api_key, created_at "
            "FROM users WHERE id = ?",
            (user_id,),
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            api_key=row["api_key"],
            created_at=row["created_at"],
        )

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Busca usuário por username."""
        rows = self._db.query(
            "SELECT id, username, email, api_key, created_at "
            "FROM users WHERE username = ?",
            (username.strip().lower(),),
            limit=1,
        )
        if not rows:
            return None
        row = rows[0]
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            api_key=row["api_key"],
            created_at=row["created_at"],
        )

    def verify_credentials(self, username: str, password: str) -> bool:
        """Confere usuário+senha **sem** abrir sessão.

        Usado no vínculo do Telegram (`/entrar`): valida a credencial da conta
        sem criar uma sessão web que ninguém vai usar.
        """
        rows = self._db.query(
            "SELECT password_hash FROM users WHERE username = ?",
            (username.strip().lower(),),
            limit=1,
        )
        return bool(rows) and _verify_password(password, rows[0]["password_hash"])

    # -- Vínculo do Telegram (chat_id → conta) --------------------------------

    def link_telegram(self, chat_id: Any, username: str) -> bool:
        """Vincula um chat do Telegram a uma conta. False se a conta não existe."""
        nome = username.strip().lower()
        if self.get_user_by_username(nome) is None:
            return False
        chave = str(chat_id)
        agora = time.time()
        if self.telegram_username(chave) is None:
            self._db.execute(
                "INSERT INTO telegram_links (chat_id, username, linked_at) "
                "VALUES (?, ?, ?)",
                (chave, nome, agora),
            )
        else:
            self._db.execute(
                "UPDATE telegram_links SET username = ?, linked_at = ? "
                "WHERE chat_id = ?",
                (nome, agora, chave),
            )
        log.info("Chat do Telegram vinculado", chat_id=chave, username=nome)
        return True

    def telegram_username(self, chat_id: Any) -> Optional[str]:
        """Conta vinculada a um chat do Telegram (ou None)."""
        rows = self._db.query(
            "SELECT username FROM telegram_links WHERE chat_id = ?",
            (str(chat_id),),
            limit=1,
        )
        return rows[0]["username"] if rows else None

    def unlink_telegram(self, chat_id: Any) -> bool:
        """Remove o vínculo de um chat. True quando havia vínculo."""
        return bool(self._db.execute(
            "DELETE FROM telegram_links WHERE chat_id = ?", (str(chat_id),)
        ))

    def rotate_api_key(self, user_id: int) -> str:
        """Gera uma nova API key para o usuário. Retorna a nova chave."""
        new_key = _generate_api_key()
        self._db.execute(
            "UPDATE users SET api_key = ? WHERE id = ?",
            (new_key, user_id),
        )
        log.info("API key rotacionada", user_id=user_id)
        return new_key

    def change_password(self, user_id: int, current: str, new: str) -> None:
        """Troca a senha do usuário — EXIGE a senha atual.

        Mesmo com a sessão válida, a troca sem a senha atual permitiria que
        quem roubar o token assumisse a conta permanentemente. O mínimo de 6
        caracteres é o mesmo do registro.

        Raises:
            AuthError: 400 senha nova curta; 401 senha atual errada.
        """
        rows = self._db.query(
            "SELECT password_hash FROM users WHERE id = ?",
            (user_id,),
            limit=1,
        )
        if not rows or not _verify_password(current, rows[0]["password_hash"]):
            raise AuthError("Senha atual incorreta", 401)
        if len(new) < 6:
            raise AuthError("Senha deve ter pelo menos 6 caracteres", 400)
        new_hash = _hash_password(new)
        self._db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, user_id),
        )
        log.info("Senha alterada pelo próprio usuário", user_id=user_id)

    def delete_user(self, user_id: int) -> bool:
        """Remove a conta (admin). False quando o id não existe.

        O histórico de conversas NÃO é apagado aqui — é balde separado
        (conversation_messages por username) e o admin usa DELETE /history/
        quando quiser removê-lo também.
        """
        rows = self._db.query(
            "SELECT id FROM users WHERE id = ?", (user_id,), limit=1
        )
        if not rows:
            return False
        # Sessões e vínculo do Telegram morrem junto com a conta — sem eles
        # sobrariam linhas órfãs e tokens ainda válidos de conta inexistente.
        self._db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self._db.execute(
            "DELETE FROM telegram_links WHERE username = ("
            "SELECT username FROM users WHERE id = ?)",
            (user_id,),
        )
        self._db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        log.info("Conta removida pelo admin", user_id=user_id)
        return True

    def count_sessions(self, user_id: int) -> int:
        """Sessões VÁLIDAS (não expiradas) de um usuário."""
        now = time.time()
        rows = self._db.query(
            "SELECT COUNT(*) AS cnt FROM sessions "
            "WHERE user_id = ? AND expires_at > ?",
            (user_id, now),
            limit=1,
        )
        return int(rows[0]["cnt"]) if rows else 0

    def count(self) -> int:
        """Quantidade de usuários registrados."""
        return int(self._db.scalar("SELECT COUNT(*) FROM users") or 0)

    def list_users(self) -> list[dict[str, Any]]:
        """Lista todos os usuários (sem password_hash)."""
        return self._db.query(
            "SELECT id, username, email, api_key, created_at FROM users "
            "ORDER BY created_at"
        )


# ---------------------------------------------------------------------------
# LoginGuard — freio contra força bruta em POST /auth/login
# ---------------------------------------------------------------------------

class LoginGuard:
    """Limita tentativas de login para conter força bruta / password spraying.

    Conta falhas em duas chaves independentes:
      - ``("user", ip, username)`` — trava a conta para aquele IP depois de
        ``max_attempts`` falhas na janela;
      - ``("ip", ip)`` — soma falhas de QUALQUER username e trava o IP
        inteiro depois de ``ip_max_attempts`` (default ``3 × max_attempts``;
        pega o ataque que troca o username a cada tentativa).

    Um login bem-sucedido zera a chave da conta — mas NÃO a do IP, senão o
    atacante com uma conta válida reiniciaria o contador de spraying.

    O ``clock`` é injetável (default ``time.monotonic``) para teste
    determinístico. Thread-safe (o APIServer é multi-thread).

    Limitação conhecida: atrás de reverse proxy, ``client_address`` é o IP do
    proxy; a chave por username continua valendo, mas a de IP agrupa todo o
    tráfego externo. Não interpretar ``X-Forwarded-For`` sem proxy confiável
    (seria trivialmente forjável).
    """

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_s: float = 300.0,
        lockout_s: float = 900.0,
        ip_max_attempts: Optional[int] = None,
        clock: Optional[Any] = None,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        # O teto do IP é mais folgado que o da conta: o do IP soma falhas de
        # vários usernames (spraying), mas não pode punir um usuário legítimo
        # que erra a senha algumas vezes em contas diferentes do mesmo NAT.
        self.ip_max_attempts = max(
            1,
            int(ip_max_attempts)
            if ip_max_attempts is not None
            else self.max_attempts * 3,
        )
        self.window_s = max(1.0, float(window_s))
        self.lockout_s = max(1.0, float(lockout_s))
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._failures: dict[tuple[str, ...], list[float]] = {}
        self._locked_until: dict[tuple[str, ...], float] = {}

    def retry_after(self, ip: str, username: str) -> float:
        """Segundos restantes de bloqueio para (ip, username); 0 = liberado."""
        with self._lock:
            now = self._clock()
            return max(
                self._remaining(("user", ip, username), now),
                self._remaining(("ip", ip), now),
            )

    def register_failure(self, ip: str, username: str) -> float:
        """Conta uma falha de login; retorna os segundos de bloqueio agora."""
        with self._lock:
            now = self._clock()
            self._bump(("user", ip, username), self.max_attempts, now)
            self._bump(("ip", ip), self.ip_max_attempts, now)
            self._gc(now)
            return max(
                self._remaining(("user", ip, username), now),
                self._remaining(("ip", ip), now),
            )

    def reset(self, ip: str, username: str) -> None:
        """Login bem-sucedido: limpa as falhas da conta (não as do IP)."""
        with self._lock:
            key = ("user", ip, username)
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    # -- Internos -------------------------------------------------------------

    def _remaining(self, key: tuple[str, ...], now: float) -> float:
        until = self._locked_until.get(key)
        if until is None:
            return 0.0
        if until <= now:
            self._locked_until.pop(key, None)
            return 0.0
        return until - now

    def _bump(self, key: tuple[str, ...], limit: int, now: float) -> None:
        # Já bloqueado: não estende a punição com cada nova tentativa.
        if now < self._locked_until.get(key, 0.0):
            return
        stamps = self._failures.setdefault(key, [])
        cutoff = now - self.window_s
        stamps[:] = [t for t in stamps if t > cutoff]
        stamps.append(now)
        if len(stamps) >= limit:
            self._locked_until[key] = now + self.lockout_s
            stamps.clear()

    def _gc(self, now: float) -> None:
        """Descarta chaves expiradas — memória limitada pelo tráfego recente."""
        cutoff = now - self.window_s
        for key, until in list(self._locked_until.items()):
            if until <= now:
                self._locked_until.pop(key, None)
        for key, stamps in list(self._failures.items()):
            if not stamps or stamps[-1] <= cutoff:
                self._failures.pop(key, None)

    def snapshot(self) -> dict[str, Any]:
        """Estado atual (observabilidade/teste)."""
        with self._lock:
            now = self._clock()
            return {
                "locked_keys": sum(
                    1 for until in self._locked_until.values() if until > now
                ),
                "tracked_keys": len(self._failures),
            }
