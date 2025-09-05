# Phoenix Dev

More info:  
[Telegram Channel](https://t.me/phoenix_w3)  
[Telegram Chat](https://t.me/phoenix_w3_space)

[Инструкция на русcком](https://phoenix-14.gitbook.io/phoenix/proekty/kite-ai)</br>


## Kite AI
Kite AI is a Layer-1 blockchain for AI, creating an agentic economy where AI agents, data providers, and creators interact with cryptographic identities, governance, and payments. It uses Proof of Attributed Intelligence (PoAI) to fairly reward contributions.


## Functionality
- Faucet onchain
- Faucet portal
- Daily quiz
- Onboarding quiz
- AI agent actions
- Swaps
- Mint Badge NFT
- Bridge
- Refferals


## Requirements
- Python version 3.10 - 3.12 
- Private keys EVM
- Proxy (optional)


## Installation
1. Clone the repository:
```
git clone https://github.com/Phoenix0x-web3/kite_ai.git
cd kite_ai
```

2. Install dependencies:
```
python install.py
```

3. Activate virtual environment: </br>

`For Windows`
```
venv\Scripts\activate
```
`For Linux/Mac`
```
source venv/bin/activate
```

4. Run script
```
python main.py
```

## Project Structure
```
pharos_network/
├── data/                   #Web3 intarface
├── files/
|   ├── private_keys.txt    # Private keys EVM
|   ├── proxy.txt           # Proxy addresses (optional)
|   ├── wallets.db          # Database
│   └── settings.yaml       # Main configuration file
├── functions/              # Functionality
└── utils/                  # Utils
```
## Configuration

### 1. files folder
- `private_keys.txt`: Private keys EVM
- `proxy.txt`: One proxy per line (format: `http://user:pass@ip:port`)

### 2. Main configurations
```yaml
# Whether to encrypt private keys
private_key_encryption: true

# Number of threads to use for processing wallets
threads: 1

#BY DEFAULT: [0,0] - all wallets
#Example: [2, 6] will run wallets 2,3,4,5,6
#[4,4] will run only wallet 4
range_wallets_to_run: [0, 0]

#Check for github updates
check_git_updates: true

# BY DEFAULT: [] - all wallets
# Example: [1, 3, 8] - will run only 1, 3 and 8 wallets
exact_wallets_to_run: []

# the log level for the application. Options: DEBUG, INFO, WARNING, ERROR
log_level : INFO

# Delay before running the same wallet again after it has completed all actions (1 - 2 hrs default)
random_pause_wallet_after_completion:
  min: 3600
  max: 7200

# Random pause between actions in seconds
random_pause_between_actions:
  min: 5
  max: 60

# Random pause to start wallet in seconds
random_pause_start_wallet:
  min: 0
  max: 60
```

### 3. Module Configurations

```yaml
Dialog with agents:
# Dialogs with AI count
ai_dialogs_count:
  min: 2
  max: 5  
```

```yaml
Swaps:
# Onchain Swaps count
swaps_count:
  min: 1
  max: 5

# Onchain Swaps percent
swaps_percent:
  min: 10
  max: 15 
```  
```yaml
Refferals:
# Invite Codes for kiteAi network, example [invite_code1, invite_code2].You can leave it empty, and the script will use random referral codes from your database.
invite_codes: []
``` 

## Usage

For your security, you can enable private key encryption by setting `private_key_encryption: true` in the `settings.yaml`. If set to `false`, encryption will be skipped.

On first use, you need to fill in the `private_keys.txt` file once. After launching the program, go to `DB Actions → Import wallets to Database`.
<img src="https://imgur.com/YYd3tMe.png" alt="Preview" width="600"/>

If encryption is enabled, you will be prompted to enter and confirm a password. Once completed, your private keys will be deleted from the private_keys.txt file and securely moved to a local database, which is created in the files folder.

<img src="https://imgur.com/2J87b4E.png" alt="Preview" width="600"/>

If you want to update proxy/twitter/discord/email you need to make synchronize with DB. After you made changes in these files, please choose this option.

<img src="https://imgur.com/lXT6FHn.png" alt="Preview" width="600"/>

Once the database is created, you can start the project by selecting `Kite AI → Random Activity`.

<img src="https://imgur.com/KWocACZ.png" alt="Preview" width="600"/>





