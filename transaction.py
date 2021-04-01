import math
from decimal import Decimal

class Transaction:
    def __init__(
        self,
        transaction: dict,
    ):
        """
        type: buy / sell
        block_number: number of ETH block tx occurred in
        totx_digg_supply: time of tx total digg supply
        totx_digg_price: {
            wbtc: wbtc / digg
            eth: eth / digg based on wbtc price
            usdc: usdc / digg based on wbtc price
        }
        raw_digg_amount: amount of DIGG token tx'd
        market_cap_pct: raw_digg_amount / totx_digg_supply -> percentage of digg supply tx'd
        """
        self.block_number = transaction.get('blockNumber')
        self.timestamp = transaction.get('timeStamp')
        self.from_address = transaction.get('from')
        self.to_address = transaction.get('to')
        self.value = Decimal(transaction.get('value'))
        self.token_decimal = int(transaction.get('tokenDecimal', 0))
        self.token_amount = self.value / Decimal(math.pow(10, self.token_decimal))
        self.tx_type = transaction.get('type')

        self.totx_digg_supply = transaction.get('totx_supply')
        self.totx_digg_price = transaction.get('totx_price')
        self.market_cap_pct = self.token_amount / self.totx_digg_supply
        self.totx_market_cap_price = self._get_market_cap_price()

    def _get_digg_supply(self, timestamp: str) -> float:
        return float(1)

    def _get_digg_price(self, block_number: str) -> dict:
        return {}
    
    def _get_market_cap_price(self) -> dict:
        mcap_price = {}
        mcap_price["mcap_usdc"] = self.totx_digg_price["digg_usdc_price"] * self.totx_digg_supply
        mcap_price["mcap_wbtc"] = self.totx_digg_price["digg_wbtc_price"] * self.totx_digg_supply
        
        return mcap_price
