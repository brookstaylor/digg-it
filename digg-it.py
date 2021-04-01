from bs4 import BeautifulSoup as soup
from datetime import datetime
from decimal import Decimal
from etherscan import Etherscan
import json
import logging
import requests
import sys
import time
from web3 import Web3

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

logger = logging.getLogger('digg-it')
logger.setLevel(logging.DEBUG)

ETHERSCAN_API_KEY = "***REMOVED***"
DIGG_ADDRESS = "0x798d1be841a82a273720ce31c822c61a67a601c3"
USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WBTC_ADDRESS = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
WBTC_DIGG_PAIR_ID = "0xe86204c4eddd2f70ee00ead6805f917671f56c52"
WBTC_USDC_PAIR_ID = "0x004375dff511095cc5a197a54140a24efef3a416"
DIGG_START_BLOCK = 11668293

TEST_ADDRESS = "0xB1AdceddB2941033a090dD166a462fe1c2029484"
# "0xfCcd515d395FcC855Fa56AE273d7837A2Db57B7c"
UNISWAP_SUBGRAPH = 'https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2'
UNISWAP_POOL_QUERY = """
    query($pairId: String!, $blockNumber: Int) {
        pair(
            block: { number: $blockNumber }
            id: $pairId
        ) {
            id
            liquidityProviderCount
            reserveUSD
            token0 {
                name
            }
            token0Price
            token1 {
                name
            }
            token1Price
            volumeToken0
            volumeToken1
            volumeUSD
        }
    }
    """

from transaction import Transaction

def get_rebases(session):
    r = session.get("https://digg.finance/")
    digg_supply_data = soup(r.content, "html.parser")

    rebases = []
    for row in digg_supply_data.find_all("table")[0].find_all("tr")[1:]:
        rebase = {}
        rebase["tx"] = row.contents[0].a['href'].split('/')[-1]
        rebase["time"] = row.contents[1].text
        rebase["supply"] = row.contents[2].text
        rebase["change"] = row.contents[3].text
        rebases.append(rebase)
    
    return rebases

def get_erc20_token_txs(start_block, user_address, token_address):
    eth = Etherscan(ETHERSCAN_API_KEY)
    last_block = get_last_block(eth)

    all_txs = eth.get_erc20_token_transfer_events_by_address(
        address=user_address,
        startblock=start_block,
        endblock=last_block,
        sort='asc'
    )

    token_txs = []
    for tx in all_txs:
        if tx['contractAddress'] == token_address:
            token_txs.append(tx)
    
    return token_txs


def get_last_block(eth):
    return eth.get_block_number_by_timestamp(timestamp=round(time.time()), closest="before")


def get_digg_supply(tx_timestamp, rebases):
    """
    {
        'tx': '0x8a20261d9443bf148b34b3767345f3992efd49bd96c9424918d6a17800a31c75',
        'time': '2021-03-30 20:03:39',
        'supply': '2638.800',
        'change': '-1.90%'
    }
    """
    tx_datetime = datetime.fromtimestamp(int(tx_timestamp))

    for rebase in rebases:
        rebase_datetime = datetime.strptime(rebase['time'], "%Y-%m-%d %H:%M:%S")
        if tx_datetime >= rebase_datetime:
            return Decimal(rebase['supply'])
    
    return Decimal(rebases[-1]['supply'])

    # raise ValueError("Something went wrong, supply could not be determined for transaciton at time ", tx_datetime)

def get_digg_price(session, block_number: int):
    price = {}

    wbtc_in_usdc = get_wbtc_usdc_price(session, block_number)

    price["digg_wbtc_price"] = get_digg_wbtc_price(session, block_number)
    price["digg_usdc_price"] = wbtc_in_usdc * price["digg_wbtc_price"]
    price["wbtc_usdc_price"] = wbtc_in_usdc

    return price

def get_digg_wbtc_price(session, block_number: int):
    query = UNISWAP_POOL_QUERY

    variables = {
        "pairId": WBTC_DIGG_PAIR_ID,
        "blockNumber": block_number
    } 

    request = session.post(UNISWAP_SUBGRAPH, json={'query': UNISWAP_POOL_QUERY, 'variables': variables})
    logger.info(f"request response:")

    return Decimal(request.json()["data"]["pair"]["token0Price"])

def get_wbtc_usdc_price(session, block_number: int):

    variables = {
        "pairId": WBTC_USDC_PAIR_ID,
        "blockNumber": block_number
    } 

    request = session.post(UNISWAP_SUBGRAPH, json={'query': UNISWAP_POOL_QUERY, 'variables': variables})
    logger.info(f"wbtc usdc response: {request.json()}")

    return Decimal(request.json()["data"]["pair"]["token1Price"])

if __name__ == "__main__":
    s = requests.Session()
    current_supply = s.get(f"https://api.etherscan.io/api?module=stats&action=tokensupply&contractaddress={DIGG_ADDRESS}&tag=latest&apikey={ETHERSCAN_API_KEY}")

    """
    "pair": {
        "id": "0xe86204c4eddd2f70ee00ead6805f917671f56c52",
        "liquidityProviderCount": "0",
        "reserveUSD": "9198210.378534566939584941735488929",
        "token0": {
            "name": "Wrapped BTC"
        },
        "token0Price": "0.7566654897357709671863456666209259",
        "token1": {
            "name": "Digg"
        },
        "token1Price": "1.321587958701806141715211543500411",
        "volumeToken0": "5148.34846095",
        "volumeToken1": "4510.513624929",
        "volumeUSD": "0"
        }
    }

    USD val of WBTC in pool = volumeToken0 * WBTC/USDC price
    USD val of DIGG in pool = volumeToken1 * WBTC/USDC price * token0Price

    DIGG price per token = WBTC/USDC price * token0Price 
    (token0Price is digg per 1 WBTC)
    """


    """
    simplest case:

    get tx

    get digg price at time of tx
        where digg price = market pct at time of purchase * PIT price of digg
    get digg price now

    difference is gain / loss on trade


    workflow

    get digg transactions of address

    for each transaction
    
        if transaction is buy: 
            get percentage of total market acquired (purchase amt / total digg supply at that block)
            get price of digg at that block (btc eth usdc)
            
            cost basis usdc = price of digg usdc * market acquired
            cost basis btc = price of digg wbtc * market acquired
            cost basis eth = price of digg eth * market acquired
            
            current amt usdc = price of digg usdc * market acquired
            current amt btc = price of digg wbtc * market acquired
            curretn amt eth = price of digg eth * market acquired
            
            pct_change = (current - acquired) / acquired
        
    
        if transaction is sell:
    
    
    
    need to handle 
    """
    start = time.time()
    logger.info(f"Started at {start}")

    logger.info("Getting rebases")
    rebases = get_rebases(s)
    logger.info("Getting transactions")
    digg_txs = get_erc20_token_txs(DIGG_START_BLOCK, TEST_ADDRESS, DIGG_ADDRESS)

    formatted_txs = []

    logger.info("Formatting transactions")
    for tx in digg_txs:
        if tx['to'] == str.lower(TEST_ADDRESS):
            tx['type'] = 'buy'
        else:
            tx['type'] = 'sell'
        tx['totx_supply'] = get_digg_supply(tx['timeStamp'], rebases)
        tx['totx_price'] = get_digg_price(s, int(tx['blockNumber']))
        logger.info("done")
        formatted_txs.append(Transaction(tx))
    
    logger.info("Get trading profit")
    digg_mcap_pct = []
    digg_usdc_mcap_price = []
    digg_wbtc_mcap_price = []
    wbtc_profit = 0
    usdc_profit = 0

    for tx in formatted_txs:
        digg_usdc_mcap = tx.totx_digg_supply * tx.totx_digg_price['digg_usdc_price']
        digg_wbtc_mcap = tx.totx_digg_supply * tx.totx_digg_price['digg_wbtc_price']
        if tx.tx_type == "buy":
            digg_mcap_pct.append(tx.market_cap_pct)
            usdc_profit -= tx.market_cap_pct * digg_usdc_mcap
            wbtc_profit -= tx.market_cap_pct * digg_wbtc_mcap
        else:
            digg_mcap_pct.append(-tx.market_cap_pct)
            usdc_profit += tx.market_cap_pct * digg_usdc_mcap
            wbtc_profit += tx.market_cap_pct * digg_wbtc_mcap
        
        digg_usdc_mcap_price.append(digg_usdc_mcap)
        digg_wbtc_mcap_price.append(digg_wbtc_mcap)
    
    num_txs = len(formatted_txs)
    logger.info(f"Txs processed: {num_txs}")
    
    finish = time.time()
    logger.info(f"Finished at {finish}")
    logger.info(f"Duration: {finish - start}")
    
    
    # for tx in formatted_txs:
    #     d = {
    #         "block": tx.block_number,
    #         "type": tx.tx_type,
    #         "digg_amount": tx.token_amount,
    #         "digg_supply": tx.totx_digg_supply,
    #         "digg_price": tx.totx_digg_price,
    #         "pct_market_cap": tx.market_cap_pct
    #     }
    #     print(d)
