"""Erros do arquivo, cada um com o código de saída do processo."""


class DumpError(Exception):
    """Erro base. A mensagem está em português e é mostrada ao utilizador."""

    exit_code = 1


class ConfigError(DumpError):
    """Configuração em falta ou inválida."""


class NetworkError(DumpError):
    """Falha de rede ou resposta inesperada do servidor."""


class ValidationError(DumpError):
    """Erro duro nos dados. Nada é escrito."""

    exit_code = 2

    def __init__(self, messages):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = list(messages)
        super().__init__("\n".join(self.messages))


class ImmutabilityError(ValidationError):
    """O ficheiro de um dia já existe e o recalculado é diferente."""


class IntegrityError(DumpError):
    """A verificação de integridade do repositório falhou."""

    exit_code = 3
