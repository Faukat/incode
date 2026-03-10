def autenticar_usuario(token: str) -> bool:
    if not token:
        return False
    return token == "token-valido"


def processar_pagamento(valor: int) -> str:
    if valor <= 0:
        raise ValueError("Valor invalido")
    return "pagamento-aprovado"
