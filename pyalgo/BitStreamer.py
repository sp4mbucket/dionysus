#
# SMA Crossover example
#
# Trade events get notified via the call to onBars. No need to manually subscribe.
# Order book update events are handled by manually subscribing to 
#   pyalgotrade.bitstamp.barfeed.LiveTradeFeed.getOrderBookUpdateEvent. 
# This is needed to be up to date with latest bid and ask prices.
#
# http://gbeced.github.io/pyalgotrade/docs/v0.17/html/bitcoin.html
#
# Added spread member
#
from pyalgotrade.bitstamp import barfeed
from pyalgotrade.bitstamp import broker
from pyalgotrade import strategy
from pyalgotrade.technical import ma
from pyalgotrade.technical import cross
import urllib
import sys

class Strategy(strategy.BaseStrategy):

    # init: Initialize base strategy, instrument, prices series.
    # set SMA period 20, feed to prices
    # feed: BitStamp live trader feed
    # brk: PaperTradingBroker
    #
    # http://gbeced.github.io/pyalgotrade/docs/v0.17/html/dataseries.html#pyalgotrade.dataseries.bards.BarDataSeries
    #
    def __init__(self, feed, brk):
        strategy.BaseStrategy.__init__(self, feed, brk)
        self.__smaPeriod = 20
        self.__instrument = "BTC"
        self.__prices = feed[self.__instrument].getCloseDataSeries()
        self.__sma = ma.SMA(self.__prices, self.__smaPeriod)
        self.__bid = None
        self.__ask = None
        self.__spread = None
        self.__position = None
        self.__posSize = 0.2
        self.__sourceDev = "PI4"
        self.__strageyUUID = ""
        self.__logURL = "https://mosias:mosias98@quantumconfigurations.com/dionysus/index.php?%s"

        #self.initDB()

        # Subscribe to order book update events to get bid/ask prices to trade.
        feed.getOrderBookUpdateEvent().subscribe(self.__onOrderBookUpdate)

    # Callback for order book updates registered to BitStamp feed
    def __onOrderBookUpdate(self, orderBookUpdate):
        bid = orderBookUpdate.getBidPrices()[0]
        ask = orderBookUpdate.getAskPrices()[0]

        if bid != self.__bid or ask != self.__ask:
            self.__bid = bid
            self.__ask = ask
            self.__spread = ask - bid
            self.postOrderBookRecord(ask, bid, self.__spread)
            self.info("B: %s. A: %s S: %s" % (self.__bid, self.__ask, self.__spread))

    def onEnterOk(self, position):
        self.info("Position opened at %s" % (position.getEntryOrder().getExecutionInfo().getPrice()))
        self.postPosition("B", position.getEntryOrder().getExecutionInfo().getPrice(), self.__posSize, position.getShares())

    def onEnterCanceled(self, position):
        self.info("Position entry canceled")
        self.__position = None

    def onExitOk(self, position):
        self.info("Position closed at %s" % (position.getExitOrder().getExecutionInfo().getPrice()))
        self.postPosition("S", position.getExitOrder().getExecutionInfo().getPrice(), self.__posSize, position.getShares())
        self.__position = None

    def onExitCanceled(self, position):
        # If the exit was canceled, re-submit it.
        self.__position.exitLimit(self.__bid)

    def postOrderBookRecord(self, ask, bid, spread):
        params = urllib.urlencode({'op': 'ORDER_BOOK', 'bitstream': 1, 'ask': ask, 'bid': bid, 'spread': self.__spread})
        self.postRecord(params)

    def postTradeLog(self, price, volume):
        params = urllib.urlencode({'op': 'TRADE_LOG', 'bitstream': 1, 'price': price, 'volume': volume, 'sma': self.__sma[-1]})
        self.postRecord(params)

    def postPosition(self, pos_type, ask, pos_size, shares):
        params = urllib.urlencode({'op': 'POSITION', 'pos_type': pos_type, 'bitstream': 1, 'ask': ask, 'pos_size': pos_size, 'shares': shares, 'sma': self.__sma[-1]})
        self.postRecord(params)

    def postRecord(self, params):
        try:
            urlHand = urllib.urlopen(self.__logURL % params)
            resp=urlHand.read()
            urlHand.close()
            return resp
        except:
            e = sys.exc_info()[0]
            self.info("Exception: %s" % (e))
            #print urlHand.geturl()
            #print urlHand.read()

    #def initDB(self):
        #params = urllib.urlencode({'op': 'HARD_INIT', 'smaperiod': self.__smaPeriod, 'position_unit_size': self.__posSize,'instrument': self.__instrument})
        #self.postRecord(params)

    # This is the trading decision algorithm.
    #
    # cross_above: Checks for a cross above conditions over the specified period between two DataSeries objects.
    #   It returns the number of times values1 crossed above values2 during the given period.
    #
    #   Determine the cross_above of the prices series with the SMA.  If so, indicates to enter a long position.
    #
    # cross_below: Checks for a cross below conditions over the specified period between two DataSeries objects.
    #   It returns the number of times values1 crossed below values2 during the given period.
    # 
    #   Determine the cross_below of the prices series with the SMA.  If so, indicates to sell a long position.
    #
    # Trade events get notified via the call to onBars. No need to manually subscribe.
    #
    # http://gbeced.github.io/pyalgotrade/docs/v0.17/html/bar.html#pyalgotrade.bar.Bar
    #
    def onBars(self, bars):
        bar = bars[self.__instrument]
        self.postTradeLog(bar.getClose(), bar.getVolume())
        self.info("Price: %s. Volume: %s." % (bar.getClose(), bar.getVolume()))

def main():
    # Create BitStamp feed
    barFeed = barfeed.LiveTradeFeed()

    # cash = 5000
    # bars = BitStamp live feed
    # fee = 0.5 % per order
    brk = broker.PaperTradingBroker(5000, barFeed)

    strat = Strategy(barFeed, brk)

    strat.run()

if __name__ == "__main__":
    main()
