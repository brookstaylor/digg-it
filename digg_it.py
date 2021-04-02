from bs4 import BeautifulSoup as soup
from datetime import datetime
from decimal import Decimal
from etherscan import Etherscan
import json
import logging
import os
import requests
import sys
import time
from web3 import Web3
from constants import (
    REBASE_DELTA_ADDRESS,
    DIGG_ADDRESS,
    USDC_ADDRESS,
    WBTC_ADDRESS,
    WBTC_DIGG_PAIR_ID,
    WBTC_USDC_PAIR_ID,
    DIGG_INITIAL_SUPPLY,
    DIGG_START_BLOCK,
    ETH_BLOCKS_PER_DAY,
    TEST_ADDRESS,
    UNISWAP_SUBGRAPH,
)

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

logger = logging.getLogger("digg-it")
logger.setLevel(logging.DEBUG)
# coingecko: digg, badger-sett-digg

from transaction import Transaction
from digg_api import DiggApi

if __name__ == "__main__":

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
    """
    start = time.time()
    logger.info(f"Started at {start}")

    api = DiggApi()

    logger.info("Getting rebases")
    rebases = api.get_rebases()
    logger.info("Getting transactions")
    digg_txs = api.get_erc20_token_txs(DIGG_START_BLOCK, TEST_ADDRESS, DIGG_ADDRESS)

    formatted_txs = []

    logger.info("Formatting transactions")
    for tx in digg_txs:
        if tx["to"] == str.lower(TEST_ADDRESS):
            tx["type"] = "buy"
        else:
            tx["type"] = "sell"
        tx["totx_supply"] = api.get_digg_supply(tx["timeStamp"], rebases)
        tx["totx_price"] = api.get_digg_price(int(tx["blockNumber"]))
        formatted_txs.append(Transaction(tx))

    logger.info("Get trading profit")
    digg_mcap_pct = []
    digg_usdc_mcap_price = []
    digg_wbtc_mcap_price = []
    wbtc_profit = 0
    usdc_profit = 0

    for tx in formatted_txs:
        digg_usdc_mcap = tx.totx_digg_supply * tx.totx_digg_price["digg_usdc_price"]
        digg_wbtc_mcap = tx.totx_digg_supply * tx.totx_digg_price["digg_wbtc_price"]
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

    logger.info(f"Getting historic market cap")
    api.get_historic_market_cap_since_block(DIGG_START_BLOCK)

    finish = time.time()
    logger.info(f"Finished at {finish}")
    logger.info(f"Duration: {finish - start}")

