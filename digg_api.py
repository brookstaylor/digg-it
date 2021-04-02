from bs4 import BeautifulSoup as soup
from datetime import datetime
from decimal import Decimal
from etherscan import Etherscan
import logging
import os
import requests
import time

from constants import (
    REBASE_DELTA_ADDRESS,
    DIGG_ADDRESS,
    USDC_ADDRESS,
    WBTC_ADDRESS,
    WBTC_DIGG_PAIR_ID,
    WBTC_USDC_PAIR_ID,
    DIGG_INITIAL_SUPPLY,
    DIGG_START_BLOCK,
    ETHERSCAN_API_KEY,
    ETH_BLOCKS_PER_DAY,
    UNISWAP_SUBGRAPH,
    TEST_ADDRESS,
)

logger = logging.getLogger("digg-it")
logger.setLevel(logging.DEBUG)

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


class DiggApi:
    def __init__(self):
        self.session = requests.Session()
        self.eth = Etherscan(ETHERSCAN_API_KEY)
        self.latest_block = self.get_latest_block()
        self.rebases = self.get_rebases()

    def get_latest_block(self) -> int:
        return int(
            self.eth.get_block_number_by_timestamp(
                timestamp=round(time.time()), closest="before"
            )
        )

    def get_rebases(self) -> list:
        r = self.session.get("https://digg.finance/")
        digg_supply_data = soup(r.content, "html.parser")

        rebases = []
        for row in digg_supply_data.find_all("table")[0].find_all("tr")[1:]:
            rebase = {}
            rebase["tx"] = row.contents[0].a["href"].split("/")[-1]
            rebase["time"] = row.contents[1].text
            rebase["supply"] = row.contents[2].text
            rebase["change"] = row.contents[3].text
            rebases.append(rebase)

        return rebases

    def get_current_supply(self):
        current_supply = self.session.get(
            f"https://api.etherscan.io/api?module=stats&action=tokensupply&contractaddress={DIGG_ADDRESS}&tag=latest&apikey={ETHERSCAN_API_KEY}"
        )

    def get_historic_market_cap_since_block(self, block_number: int) -> list:
        """
        Returns list of market cap every 2000 blocks (twice a day) since block_number.

        return: list(list(timestamp, totx_digg_usdc_mcap, totx_digg_wbtc_mcap))
        """
        historic_market_cap = []

        logger.info(f"Getting historic market cap since: block {block_number}")

        while block_number < self.latest_block:
            entry = []
            timestamp = self.eth.get_block_reward_by_block_number(
                block_no=block_number
            )["timeStamp"]
            supply = self.get_digg_supply(timestamp, self.rebases)
            wbtc_price = self.get_digg_wbtc_price(block_number)
            # The digg wbtc pool didn't exist until a few thousand blocks after the 
            # digg contract was created. Only append entries for blocks with the pool.
            if wbtc_price:
                usdc_price = self.get_wbtc_usdc_price(block_number)
                entry.append(timestamp)
                entry.append(supply * usdc_price)
                entry.append(supply * wbtc_price)
                historic_market_cap.append(entry)
            block_number += int(ETH_BLOCKS_PER_DAY / 2)

        logger.info(
            f"Grabbed historic market cap for {len(historic_market_cap)} entries"
        )
        logger.info(historic_market_cap)

        return historic_market_cap

    def get_digg_supply(self, tx_timestamp, rebases) -> Decimal:
        """
        {
            'tx': '0x8a20261d9443bf148b34b3767345f3992efd49bd96c9424918d6a17800a31c75',
            'time': '2021-03-30 20:03:39',
            'supply': '2638.800',
            'change': '-1.90%'
        }
        """
        tx_datetime = datetime.utcfromtimestamp(int(tx_timestamp))

        for rebase in rebases:
            rebase_datetime = datetime.strptime(rebase["time"], "%Y-%m-%d %H:%M:%S")
            if tx_datetime >= rebase_datetime:
                return Decimal(rebase["supply"])

        return Decimal(DIGG_INITIAL_SUPPLY)

    def get_digg_wbtc_price(self, block_number: int) -> Decimal:

        variables = {"pairId": WBTC_DIGG_PAIR_ID, "blockNumber": block_number}

        request = self.session.post(
            UNISWAP_SUBGRAPH, json={"query": UNISWAP_POOL_QUERY, "variables": variables}
        )

        logger.info(f"digg_wbtc_price: {request.json()}")

        return (
            None
            if request.json()["data"]["pair"] == None
            else Decimal(request.json()["data"]["pair"]["token0Price"])
        )

    def get_wbtc_usdc_price(self, block_number: int) -> Decimal:

        variables = {"pairId": WBTC_USDC_PAIR_ID, "blockNumber": block_number}

        request = self.session.post(
            UNISWAP_SUBGRAPH, json={"query": UNISWAP_POOL_QUERY, "variables": variables}
        )

        return Decimal(request.json()["data"]["pair"]["token1Price"])

    def get_erc20_token_txs(
        self, start_block: int, user_address: str, token_address: str
    ) -> list:

        latest_block = self.latest_block

        all_txs = self.eth.get_erc20_token_transfer_events_by_address(
            address=user_address,
            startblock=start_block,
            endblock=latest_block,
            sort="asc",
        )

        token_txs = []
        for tx in all_txs:
            if tx["contractAddress"] == token_address:
                token_txs.append(tx)

        return token_txs

    def get_digg_price(self, block_number: int) -> Decimal:
        price = {}

        # TODO: speed these calls up, right now taking too long. About 3 txs per second able to be processed
        wbtc_in_usdc = self.get_wbtc_usdc_price(block_number)

        price["digg_wbtc_price"] = self.get_digg_wbtc_price(block_number)
        price["digg_usdc_price"] = wbtc_in_usdc * price["digg_wbtc_price"]
        price["wbtc_usdc_price"] = wbtc_in_usdc

        return price
