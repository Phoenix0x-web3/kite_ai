import asyncio
import platform

import inquirer
from colorama import Fore
from inquirer import themes
from rich.console import Console

from check_python import check_python_version
from data.constants import PROJECT_NAME
from functions.activity import activity
from utils.create_files import create_files, reset_folder
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.db_import_export_sync import Export, Import, Sync
from utils.git_version import check_for_updates
from utils.output import show_channel_info

console = Console()

PROJECT_ACTIONS = [
    "1. Random Activity",
    "2. Discord Tasks",
    "3. Push Social Tasks and Bound",
    "4. Bound Wallet Address",
    "5. Checker",
    "6. Claimer",
    "Back",
]

UTILS_ACTIONS = ["1. Reset files Folder", "Back"]


async def choose_action():
    cat_question = [
        inquirer.List(
            "category",
            message=Fore.LIGHTBLACK_EX + "Choose action",
            choices=["DB Actions", PROJECT_NAME, "Utils", "Exit"],
        )
    ]

    answers = inquirer.prompt(cat_question, theme=themes.Default())
    category = answers.get("category")

    if category == "Exit":
        console.print(f"[bold red]Exiting {PROJECT_NAME}...[/bold red]")
        raise SystemExit(0)

    if category == "DB Actions":
        actions = ["Import wallets to Database", "Sync wallets with tokens and proxies", "Export Database to CSV", "Back"]

    if category == PROJECT_NAME:
        actions = PROJECT_ACTIONS

    if category == "Utils":
        actions = UTILS_ACTIONS

    act_question = [
        inquirer.List(
            "action",
            message=Fore.LIGHTBLACK_EX + f"Choose action in '{category}'",
            choices=actions,
        )
    ]

    act_answer = inquirer.prompt(act_question, theme=themes.Default())
    action = act_answer["action"]

    if action == "Import wallets to Database":
        console.print(f"[bold blue]Starting Import Wallets to DB[/bold blue]")
        await Import.wallets()
    elif action == "Sync wallets with tokens and proxies":
        console.print(f"[bold blue]Starting sync data in DB[/bold blue]")
        await Sync.sync_wallets_with_tokens_and_proxies()
    elif action == "Export Database to CSV":
        console.print(f"[bold blue]Starting Export Database to CSV[/bold blue]")
        await Export.data_to_csv()

    elif action == "1. Random Activity":
        await activity(action=1)

    elif action == "2. Discord Tasks":
        await activity(action=2)

    elif action == "3. Push Social Tasks and Bound":
        await activity(action=3)

    elif action == "4. Bound Wallet Address":
        await activity(action=4)

    elif action == "5. Checker":
        await activity(action=5)

    elif action == "6. Claimer":
        await activity(action=6)

    elif action == "1. Reset files Folder":
        console.print("This action will delete the files folder and reset it.")
        answer = input("Are you sure you want to perform this action? y/N ")
        if answer.lower() == "y":
            reset_folder()
            console.print("Files folder success reset")

    elif action == "Exit":
        console.print(f"[bold red]Exiting {PROJECT_NAME}...[/bold red]")
        raise SystemExit(0)

    await choose_action()


async def main():
    check_python_version()
    create_files()

    await check_for_updates(repo_name=PROJECT_NAME)

    db.ensure_model_columns(Wallet)

    await choose_action()


if __name__ == "__main__":
    show_channel_info(PROJECT_NAME)

    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
