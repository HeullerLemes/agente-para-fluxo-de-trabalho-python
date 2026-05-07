from datetime import datetime, timezone
import os

from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent
from trello import TrelloClient

load_dotenv()

API_KEY = os.getenv("TRELLO_API_KEY")
API_SECRET = os.getenv("TRELLO_API_SECRET")
TOKEN = os.getenv("TRELLO_TOKEN")
BOARD_NAME = "DIO"

LIST_NAMES_BY_STATUS = {
    "a fazer": ("A FAZER", "TO DO", "TODO"),
    "em andamento": ("EM ANDAMENTO", "DOING"),
    "concluido": ("CONCLUIDO", "CONCLUÍDO", "DONE"),
}

DONE_LIST_NAMES = LIST_NAMES_BY_STATUS["concluido"]


def get_temporal_context():
    now = datetime.now()
    return now.strftime("%Y/%m/%d %H:%M:%S")


def _trello_client() -> TrelloClient:
    return TrelloClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        token=TOKEN,
    )


def _get_board(client: TrelloClient, board_name: str = BOARD_NAME):
    return next(board for board in client.list_boards() if board.name == board_name)


def _list_name(name: str) -> str:
    return name.strip().upper()


def _status_lists(lists, status: str):
    status_key = status.lower().strip()

    if status_key == "todas":
        return lists

    expected_names = LIST_NAMES_BY_STATUS.get(status_key)
    if not expected_names:
        return lists

    return [lista for lista in lists if _list_name(lista.name) in expected_names]


def _due_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()

    try:
        normalized_value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized_value).date()
    except ValueError:
        return None


def adicionar_tarefa(nome_da_task: str, descricao_da_task: str, due_date: str):
    client = _trello_client()
    meu_board = _get_board(client)
    listas = meu_board.list_lists()

    minha_lista = next(
        lista
        for lista in listas
        if _list_name(lista.name) in LIST_NAMES_BY_STATUS["a fazer"]
    )

    minha_lista.add_card(
        name=nome_da_task,
        desc=descricao_da_task,
        due=due_date,
    )


def listar_tarefas(status: str = "todas"):
    client = _trello_client()
    meu_board = _get_board(client)
    listas_filtradas = _status_lists(meu_board.list_lists(), status)

    return [
        {
            "nome": card.name,
            "descricao": card.desc,
            "vencimento": card.due,
            "status": lista.name,
            "id": card.id,
        }
        for lista in listas_filtradas
        for card in lista.list_cards()
    ]


def sugerir_foco_do_dia() -> str:
    client = _trello_client()
    meu_board = _get_board(client)
    hoje = datetime.now(timezone.utc).date()

    tarefas_abertas = [
        card
        for lista in meu_board.list_lists()
        if _list_name(lista.name) not in DONE_LIST_NAMES
        for card in lista.list_cards()
    ]

    tarefas_vencidas = [
        card
        for card in tarefas_abertas
        if _due_date(card.due) and _due_date(card.due) < hoje
    ]
    tarefas_para_hoje = [
        card
        for card in tarefas_abertas
        if _due_date(card.due) == hoje
    ]

    if tarefas_vencidas:
        quantidade = len(tarefas_vencidas)
        plural = "tarefas" if quantidade != 1 else "tarefa"
        return f"Você deveria focar em {quantidade} {plural} vencidas hoje."

    if tarefas_para_hoje:
        quantidade = len(tarefas_para_hoje)
        plural = "tarefas" if quantidade != 1 else "tarefa"
        return f"Você deveria focar em {quantidade} {plural} de hoje."

    return "Você não tem tarefas vencidas ou tarefas com vencimento para hoje. Foque em sua próxima prioridade aberta."


def mudar_status_tarefa(nome_da_task: str, novo_status: str) -> str:
    try:
        client = _trello_client()
        meu_board = _get_board(client)
        listas = meu_board.list_lists()

        nomes_destino = LIST_NAMES_BY_STATUS.get(novo_status.lower().strip())
        if not nomes_destino:
            return f"❌ Status inválido. Use: 'a fazer', 'em andamento' ou 'concluido'"

        lista_destino = next(
            (lista for lista in listas if _list_name(lista.name) in nomes_destino),
            None,
        )

        if not lista_destino:
            return f"❌ Lista '{nomes_destino[0]}' não encontrada no board"

        card_encontrado = None
        lista_origem = None

        for lista in listas:
            card_encontrado = next(
                (
                    card
                    for card in lista.list_cards()
                    if card.name.lower() == nome_da_task.lower()
                ),
                None,
            )

            if card_encontrado:
                lista_origem = lista
                break

        if not card_encontrado:
            return f"❌ Card '{nome_da_task}' não encontrado"

        card_encontrado.change_list(lista_destino.id)
        return f"✅ '{nome_da_task}': {lista_origem.name} → {lista_destino.name}"
    except Exception as e:
        return f"❌ Erro: {str(e)}"


AGENT_INSTRUCTION = """
Você é um agente de organização de tarefas.
Sua função é receber uma tarefa e criar um card no Trello com o nome e descrição da tarefa.
Você deve me perguntar as atividas que tenho no dia e criar um card para cada uma delas.
Você inicia a conversa assim que for ativado, perguntando quais são as tarefas do dia.
Sempre inicie a conversa perguntando quais são as tarefas do dia informando a data com pela tool get_temporal_context,
e depois vá perguntando se tem mais alguma tarefa, até que o usuário diga que não tem mais tarefas.
Suas funções:
 1. Adicionar novas tarefas com nome e descrição
 2. Listar todas as tarefas ou filtrar por status
 3. Marcar tarefas como concluídas
 4. Remover tarefas da lista
 5. Mudar o status da tarefa (ex: de "A Fazer" para "Em Andamento" e de "Em Andamento" para "Concluído")
 6. Gerar contexto temporal (data e hora atual) para organizar as tarefas do dia
 7. Sugerir em quais tarefas o usuário deve focar hoje, priorizando tarefas vencidas e depois tarefas com vencimento para hoje
"""


root_agent = Agent(
    model="gemini-2.5-flash",
    name="root_agent",
    description="Agente de Organização de Tarefas",
    instruction=AGENT_INSTRUCTION,
    tools=[
        get_temporal_context,
        adicionar_tarefa,
        listar_tarefas,
        mudar_status_tarefa,
        sugerir_foco_do_dia,
    ],
)
