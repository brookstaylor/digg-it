from bs4 import BeautifulSoup as soup
from datetime import datetime
from decimal import Decimal
from etherscan import Etherscan
import logging
import os
import requests
import time
from web3 import Web3

from constants import (
    REBASE_DELTA_ADDRESS,
    BDIGG_ADDRESS,
    BDIGG_DECIMALS,
    DIGG_ADDRESS,
    DIGG_DECIMALS,
    USDC_ADDRESS,
    USDC_DECIMALS,
    WBTC_ADDRESS,
    WBTC_DECIMALS,
    WBTC_DIGG_PAIR_ID,
    WBTC_USDC_PAIR_ID,
    DIGG_INITIAL_SUPPLY,
    DIGG_START_BLOCK,
    ETHERSCAN_API_KEY,
    ETH_BLOCKS_PER_DAY,
    UNISWAP_SUBGRAPH,
    TEST_ADDRESS,
    DIGG_IT_INFURA_URL,
)

from abi import DIGG_CONTRACT_ABI, REBASE_DELTA_ABI

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
cache = {}


class DiggApi:
    def __init__(self):
        if cache.get("session") == None:
            cache["session"] = requests.Session()
        if cache.get("web3") == None:
            cache["web3"] == Web3(Web3.HTTPProvider(DIGG_IT_INFURA_URL))
        self.session = cache.get("session")
        self.web3 = cache.get("web3")
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

    def get_rebases_web3(self) -> list:
        # Use the supply delta contract because it has fewer transactions and is quicker to query
        # to get the full list of rebases. Could use the digg contract but it requires getting
        # more transactions because people trade with it.
        rebase_contract_address = self.web3.toChecksumAddress(REBASE_DELTA_ADDRESS)
        rebase_contract = self.web3.eth.contract(
            address=rebase_contract_address, abi=REBASE_DELTA_ABI
        )

        # get list of transactions that emit a LogRebase event
        rebase_txs = (
            rebase_contract.events.LogRebase()
            .createFilter(fromBlock=DIGG_START_BLOCK)
            .get_all_entries()
        )
        rebases = []

        for tx in rebase_txs:
            rebase = {}

            tx_hash = tx["transactionHash"].hex()
            receipt = self.web3.eth.getTransactionReceipt(tx_hash)
            tx_log = rebase_contract.events.LogRebase().processReceipt(receipt)

            rebase["tx"] = tx_hash
            rebase["block_number"] = tx_log[0]["blockNumber"]
            rebase["supply"] = tx_log[0]["args"]["totalSupply"] / DIGG_DECIMALS
            rebases.append(rebase)

        return rebases

    def get_digg_current_supply(self):
        return Decimal(
            self.session.get(
                f"https://api.etherscan.io/api?module=stats&action=tokensupply&contractaddress={DIGG_ADDRESS}&tag=latest&apikey={ETHERSCAN_API_KEY}"
            )
            / DIGG_DECIMALS
        )

    def get_historic_market_cap_since_block(self, block_number: int) -> list:
        """
        Returns list of market cap every ETH_BLOCKS_PER_DAY / 2 (twice a day) since block_number.

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
            wbtc_price = self.get_digg_wbtc_price_at_block(block_number)
            # The digg wbtc pool didn't exist until a few thousand blocks after the
            # digg contract was created. Only append entries for blocks with the pool.
            if wbtc_price:
                usdc_price = self.get_wbtc_usdc_price_at_block(block_number)
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

    def get_digg_supply(self, tx_timestamp: str, rebases: list) -> Decimal:
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

    def get_digg_wbtc_price_at_block(self, block_number: int) -> Decimal:

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

    def get_wbtc_usdc_price_at_block(self, block_number: int) -> Decimal:

        variables = {"pairId": WBTC_USDC_PAIR_ID, "blockNumber": block_number}

        request = self.session.post(
            UNISWAP_SUBGRAPH, json={"query": UNISWAP_POOL_QUERY, "variables": variables}
        )

        return Decimal(request.json()["data"]["pair"]["token1Price"])

    def get_address_erc20_token_txs(
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

    def get_digg_price_at_block(self, block_number: int) -> dict:
        price = {}

        # TODO: speed these calls up, right now taking too long. About 3 txs per second able to be processed
        wbtc_in_usdc = self.get_wbtc_usdc_price_at_block(block_number)

        price["digg_wbtc_price"] = self.get_digg_wbtc_price_at_block(block_number)
        price["digg_usdc_price"] = wbtc_in_usdc * price["digg_wbtc_price"]
        price["wbtc_usdc_price"] = wbtc_in_usdc

        return price

    def get_address_digg_balance(self, address: str) -> Decimal:
        return Decimal(
            self.get_address_token_balance(address, DIGG_ADDRESS) / DIGG_DECIMALS
        )

    def get_address_bdigg_balance(self, address: str) -> Decimal:
        return Decimal(
            self.get_address_token_balance(address, BDIGG_ADDRESS) / BDIGG_DECIMALS
        )

    def get_address_token_balance(self, wallet_address: str, token_address: str) -> int:
        return self.eth.get_acc_balance_by_token_and_contract_address(
            address=wallet_address, contract_address=token_address
        )
