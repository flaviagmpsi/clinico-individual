"""Freio contra tentativa de senha em massa (ADR-114).

Sem isto, uma lista de senhas comuns contra um e-mail conhecido roda a noite inteira sem resistência. E, num
sistema de psicólogos, a conta invadida não é "uma conta": é o prontuário de todos os pacientes daquela pessoa.

**Conta por e-mail e por endereço de IP, e o que estoura primeiro trava.** Só por IP puniria o consultório inteiro
atrás de um mesmo roteador; só por e-mail deixaria passar quem varre muitos e-mails com uma senha só — que é
justamente como a maioria dos ataques por lista funciona hoje.

Guardado no cache, e não no banco: o dado é efêmero, não precisa sobreviver a um deploy, e gravar uma linha por
tentativa seria dar ao atacante um jeito barato de encher o disco. O cache padrão do Django é por processo, e com
um processo só — que é o caso no Render — isso basta. Com mais de um, a conta se divide entre eles e o freio fica
mais frouxo, nunca mais apertado.
"""

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

TENTATIVAS_ATE_TRAVAR = 8
MINUTOS_TRAVADO = 15


def _chaves(request, email: str) -> list[str]:
    endereco = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                or request.META.get("REMOTE_ADDR", "") or "sem-ip")
    return [f"login:ip:{endereco}", f"login:email:{(email or '').strip().casefold()}"]


def travado(request, email: str) -> bool:
    return any(cache.get(chave, 0) >= TENTATIVAS_ATE_TRAVAR for chave in _chaves(request, email))


def registrar_erro(request, email: str) -> None:
    for chave in _chaves(request, email):
        # `add` só cria se não existir — é ele que faz a janela começar na primeira tentativa errada e expirar
        # sozinha, sem ninguém ter de limpar nada.
        cache.add(chave, 0, MINUTOS_TRAVADO * 60)
        try:
            cache.incr(chave)
        except ValueError:
            # A chave expirou entre o `add` e o `incr`. A janela recomeça; perder uma contagem aqui é aceitável.
            cache.set(chave, 1, MINUTOS_TRAVADO * 60)


def limpar(request, email: str) -> None:
    """Entrou: a contagem zera. Quem sabe a senha não deve ser punido por ter errado antes."""
    cache.delete_many(_chaves(request, email))


def recado() -> str:
    return (f"Muitas tentativas seguidas. Por segurança, espere {MINUTOS_TRAVADO} minutos antes de tentar de novo "
            "— ou use “Esqueci a minha senha”.")


def minutos_restantes() -> int:
    return MINUTOS_TRAVADO


def ligado() -> bool:
    """Desligável em teste, onde errar a senha de propósito é parte do que se verifica."""
    return not getattr(settings, "FREIO_DE_LOGIN_DESLIGADO", False)


def agora():
    return timezone.now()
