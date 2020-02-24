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
# 7/20/2016: Added start time and runtime as well as check to determine when the strategy
#   should be ended.  This facilitates using strategy analyzers.
#
# Added spread member
#
from pyalgotrade.bitstamp import barfeed
from pyalgotrade.bitstamp import broker
from pyalgotrade import strategy
from pyalgotrade.technical import ma
from pyalgotrade.technical import rsi
from pyalgotrade.technical import cross
from pyalgotrade.stratanalyzer import returns
from pyalgotrade.stratanalyzer import trades
from pyalgotrade.stratanalyzer import sharpe
from pyalgotrade.stratanalyzer import drawdown
import random
import urllib
import ssl
import sys
import time
import subprocess
import ConfigParser
import traceback

class Strategy(strategy.BaseStrategy):

    # init: Initialize base strategy, instrument, prices series.
    # set SMA period 20, feed to prices
    # feed: BitStamp live trader feed
    # brk: PaperTradingBroker
    #
    # http://gbeced.github.io/pyalgotrade/docs/v0.17/html/dataseries.html#pyalgotrade.dataseries.bards.BarDataSeries
    #
    def __init__(self, feed, brk):
        config = ConfigParser.ConfigParser()
        config.read('bot.cfg')
        strategy.BaseStrategy.__init__(self, feed, brk)
        self.__smaPeriod = int(config.get('main','sma_period'))
        self.__rsiPeriod = int(config.get('main','rsi_period'))
        self.__instrument = config.get('main','instrument')
        self.__prices = feed[self.__instrument].getCloseDataSeries()
        self.__sma = ma.SMA(self.__prices, self.__smaPeriod)
        self.__rsi = rsi.RSI(self.__prices, self.__rsiPeriod)
        self.__bid = None
        self.__ask = None
        self.__spread = None
        self.__position = None
        self.__posSize = float(config.get('main','position_size'))
        #self.__posSize = random.randint(45, 93)
        self.__strategyUUID = None
        self.__engine = config.get('main','engine_name')
        self.__start_time = time.time()
        self.__maxRunTime = int(config.get('main','runtime'))
        self.__logURL = "https://mosias:mosias98@dionysus.quantumconfigurations.com/dionysus/index.php?%s"
        self.__barsctr = 0
        self.__isShuttingDown = False
        self.__isExitActive = False
        self.__isOrderOpenActive = False
        self.__orderbookctr = 0
        self.__positionsctr_1 = 0
        self.__positionsctr_2 = 0
        self.__cmdTimer = time.time()
        self.__exitActiveTimer = 0
        self.__exitBid = 0
        self.__cmdTimerMax = int(config.get('main','command_run_interval'))
        self.__status = "RUNNING"
        self.__pos_type = "N"
        self.__last_pos_type = "N"

        initCtr = 0
        initMax = 5
        initDelay = 5

        while self.__strategyUUID == None and initCtr < initMax:
            self.initDB()

            if self.__strategyUUID == None:
                self.error("Strategy was not initialized, retry " + str(initCtr))
                initCtr += initCtr
                time.sleep(initDelay)
            else:
                self.info("Strategy " + self.__strategyUUID + " has been initialized.")

        if self.__strategyUUID == None:
            self.error("ERROR: Unable to initialize, shutting down")
            self.stop()
        else:
            # Subscribe to order book update events to get bid/ask prices to trade.
            feed.getOrderBookUpdateEvent().subscribe(self.__onOrderBookUpdate)

    def getStrategyUUID(self):
        return self.__strategyUUID

    def getEngine(self):
        return self.__engine

    # Callback for order book updates registered to BitStamp feed
    def __onOrderBookUpdate(self, orderBookUpdate):
        bid = orderBookUpdate.getBidPrices()[0]
        ask = orderBookUpdate.getAskPrices()[0]

        if bid != self.__bid or ask != self.__ask:
            self.__orderbookctr += 1
            self.__bid = bid
            self.__ask = ask
            self.__spread = ask - bid
            #self.postOrderBookRecord(ask, bid, self.__spread)
            self.info("B: %s. A: %s S: %s" % (self.__bid, self.__ask, self.__spread))

    def onEnterOk(self, position):
        self.__positionsctr_2 += 1
        self.__isOrderOpenActive = True
        self.__last_pos_type = self.__pos_type
        self.__pos_type = "B"
        self.postPosition(self.__pos_type, position.getEntryOrder().getExecutionInfo().getPrice(), self.__posSize, position.getShares())
        self.info("Position opened at %s" % (position.getEntryOrder().getExecutionInfo().getPrice()))

    def onEnterCanceled(self, position):
        self.info("Position entry canceled")
        self.__position = None

    def onExitOk(self, position):
        self.__last_pos_type = self.__pos_type
        self.__pos_type = "S"
        self.__position = None
        self.__exitActiveTimer = 0
        self.__exitBid = 0
        self.__isExitActive = False
        self.__isOrderOpenActive = False
        self.postPosition(self.__pos_type, position.getExitOrder().getExecutionInfo().getPrice(), self.__posSize, position.getShares())
        self.info("Position closed at %s" % (position.getExitOrder().getExecutionInfo().getPrice()))

        if self.__isShuttingDown:
            self.info("onExitOk: order closed, issuing stop() to complete shutdown.")
            self.stop()

    def onExitCanceled(self, position):
        # If the exit was canceled, re-submit it.
        self.__position.exitLimit(self.__bid)

    def postOrderBookRecord(self, ask, bid, spread):
        params = urllib.urlencode(
                {
                    'op': 'ORDER_BOOK',
                    'ask': ask,
                    'bid': bid,
                    'spread': self.__spread,
                    'strategyid': self.__strategyUUID,
                    'engine': self.__engine
                }
            )
        #self.postRecord(params)

    def postTradeLog(self, price, volume):
        params = urllib.urlencode(
                {
                    'op': 'TRADE_LOG',
                    'price': price,
                    'volume': volume,
                    'sma': self.__sma[-1],
                    'rsi': self.__rsi[-1],
                    'strategyid': self.__strategyUUID,
                    'engine': self.__engine
                }
            )
        #self.postRecord(params)

    def postPosition(self, pos_type, ask, pos_size, shares):
        exec_price = 0
        if (self.__position is not None) and \
            (self.__position.getEntryOrder() is not None) and \
                (self.__position.getEntryOrder().getExecutionInfo() is not None):
                    exec_price = self.__position.getEntryOrder().getExecutionInfo().getPrice()

        params = urllib.urlencode(
                {
                    'op': 'POSITION',
                    'pos_type': pos_type,
                    'ask': ask,
                    'pos_size': pos_size,
                    'shares': shares,
                    'sma': self.__sma[-1],
                    'rsi': self.__rsi[-1],
                    'strategyid': self.__strategyUUID,
                    'engine': self.__engine,
                    'num_bars': self.__barsctr,
                    'last_pos_type': self.__last_pos_type,
                    'is_shutting_down': str(self.__isShuttingDown),
                    'is_exit_active': str(self.__isExitActive),
                    'is_order_open_active': str(self.__isOrderOpenActive),
                    'order_book_ctr': self.__orderbookctr,
                    'exit_active_timer': self.__exitActiveTimer,
                    'engine_status': self.__status,
                    'spread': self.__spread,
                    'pos_ctr1': self.__positionsctr_1,
                    'pos_ctr2': self.__positionsctr_2,
                    'bid': self.__bid,
                    'ask': self.__ask, 
                    'exec_price': exec_price
                }
            )
        self.postRecord(params)

    def postRecord(self, params):
        try:
            gcontext = ssl._create_unverified_context()
            urlHand = urllib.urlopen(self.__logURL % params, context=gcontext)
            resp=urlHand.read()
            urlHand.close()
            return self.processCommands(resp)
        except:
            self.error("An exception occurred while posting a record.")
            traceback.print_exc(file=sys.stdout)

    # Handle commands returned from interactions with the command tower
    def processCommands(self, cmdStr):
        if cmdStr == "OK" or cmdStr == '':
            self.debug("No new commands received.")
        else:
            #self.info("RAW COMMAND STRING: " + cmdStr)
            pos = cmdStr.find(":")
            cmdID = cmdStr[0:pos]

            numParms = cmdStr.count(":") - 1
            parm1 = ""
            cmdTxt = ""

            if numParms > 0:
                #self.info("GOT PARAMETER")
                buffX = cmdStr[pos+1:]
                parmDelimPos = buffX.find(":")
                cmdTxt = buffX[0:parmDelimPos]
                parm1 = buffX[parmDelimPos+1:]
            else:
                #self.info("NO PARAMETER")
                cmdTxt = cmdStr[pos+1:]

            self.info("Command received: cmd_id=" + cmdID + ",cmd_txt=" + cmdTxt + ",param=" + parm1)
            if cmdTxt == "END":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': 'ENDING',
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
                self.shutdown()
            elif cmdTxt == "GET_SMA":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__sma[-1],
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_RUNTIME":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': time.time() - self.__start_time,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_INSTRUMENT":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__instrument,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_MAX_RUNTIME":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                            {
                                'op': 'ACK_COMMAND',
                                'cmdresponse': self.__maxRunTime,
                                'cmdid': cmdID
                            }
                        )
                self.postRecord(params)
            elif cmdTxt == "SET_MAX_RUNTIME":
                self.info("Processing command: " + cmdTxt)
                self.__maxRunTime = float(parm1)
                params = urllib.urlencode(
                            {
                                'op': 'ACK_COMMAND',
                                'cmdresponse': self.__maxRunTime,
                                'cmdid': cmdID
                            }
                        )
                self.postRecord(params)
            elif cmdTxt == "GET_COMMAND_INTERVAL":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__cmdTimerMax,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "SET_COMMAND_INTERVAL":
                self.info("Processing command: " + cmdTxt)
                self.__cmdTimerMax = float(parm1)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__cmdTimerMax,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_BARS_COUNT":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__barsctr,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_ORDER_BOOK_COUNT":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__orderbookctr,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_POSITIONS_COUNT":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': str(self.__positionsctr_1) + ":" + str(self.__positionsctr_2),
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_POSITION_ATTRIBUTE":
                self.info("Processing command: " + cmdTxt)
                respStr = "No Position Open"
		if self.__position != None:
		    if hasattr(self.__position, parm1):
		        respStr = parm1 + ":" + str(getattr(self.__position, parm1)())
                    else:
                        respStr = parm1 + ": Attribute not found"

                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': respStr,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_TRADES_COUNT":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__barsctr,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_POSITION_SIZE":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': str(self.__posSize),
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "SET_POSITION_SIZE":
                self.info("Processing command: " + cmdTxt)
                self.__posSize = float(parm1)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__posSize,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_UUID":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__strategyUUID,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "GET_STATUS":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__status,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            elif cmdTxt == "FORCE_STOP":
                self.info("Processing command: " + cmdTxt)
                self.__status = "FORCE_STOP"
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': self.__status,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
                self.forceStop()
            elif cmdTxt == "GET_EXIT_ACTIVE_DURATION":
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': ' ACK_COMMAND',
                            'cmdresponse': str(self.getExitActiveDuration()),
                            'cmdid': cmdID
                        }
                    )
            else:
                self.info("Processing command: " + cmdTxt)
                params = urllib.urlencode(
                        {
                            'op': 'ACK_COMMAND',
                            'cmdresponse': 'UNKNOWN COMMAND: ' + cmdStr,
                            'cmdid': cmdID
                        }
                    )
                self.postRecord(params)
            self.__cmdTimer = time.time()
            return cmdTxt

    def initDB(self):
        params = urllib.urlencode(
                {
                    'op': 'HARD_INIT',
                    'smaperiod': self.__smaPeriod,
                    'rsiperiod': self.__rsiPeriod,
                    'position_unit_size': self.__posSize,
                    'instrument': self.__instrument,
                    'engine': self.__engine
                }
            )
        self.__strategyUUID = self.postRecord(params)

    def getExitActiveDuration(self):
        if self.__isExitActive:
            return time.time() - self.__exitActiveTimer
        else:
            return 0

    # Check the runtime and check the command queue.
    def onIdle(self):
        self.checkRunTime()
        if (time.time() - self.__cmdTimer) > self.__cmdTimerMax:
            params = urllib.urlencode(
                    {
                        'op': 'GET_COMMAND',
                        'engine': self.__engine
                    }
                )
            self.postRecord(params)
            params = urllib.urlencode(
                    {
                         'op': 'SET_STATUS',
                         'engine': self.__engine,
                         'strategyid': self.__strategyUUID,
                         'status': self.__status
                    }
                )
            self.postRecord(params)
            self.__cmdTimer = time.time()

    def checkRunTime(self):
        if (time.time() - self.__start_time) > self.__maxRunTime and not self.__isShuttingDown:
            self.info("Stopping strategy " + self.__strategyUUID)
            self.shutdown()

    #############################################################################################################
    #
    # Shutdown
    #
    # Determine if a position exists, is it in exit, open, etc.
    # 
    # See onExitOk, which determines shutdown based on __isShuttingDown
    #
    #############################################################################################################
    def shutdown(self):
        self.info("Attempting to shut down clean")
        self.__isShuttingDown = True

        if self.__position is not None:

            try:
                # Position exists, what state is it in and how can it be shutdown clean
                self.info("Position exists, attempting exit processing")

                # Order is currently open, need to exit
                if ( self.__position is not None and not self.__position.exitActive() ) and self.__position.isOpen():
                    self.info("Order is currently open, issuing exitLimit")
                    self.__position.exitLimit(self.__bid)
                    self.__status = "SHUTDOWN_PENDING_EXIT"
                    params = urllib.urlencode(
                            {
                                'op': 'SET_STRATEGY_STATUS',
                                'strategyid': self.__strategyUUID,
                                'status': self.__status
                            }
                        )
                    self.postRecord(params)

                # Order is currently being opened, need to issue cancel
                if self.__position is not None and self.__position.entryActive() and not self.__position.exitActive():
                    self.info("Order is currently being opened, need to issue cancel")
                    self.__position.cancelEntry()
                    self.__status = "SHUTDOWN_PENDING_CANCEL"
                    params = urllib.urlencode(
                            {
                                'op': 'SET_STRATEGY_STATUS',
                                'strategyid': self.__strategyUUID,
                                'status': self.__status
                            }
                        )
                    self.postRecord(params)

                # Position is in exitActive, let it finish
                if self.__position is not None and self.__position.exitActive():
                    self.info("Order is exitActive")
                    self.__status = "SHUTDOWN_PENDING_EXIT_ACTIVE"
                    params = urllib.urlencode(
                            {
                                'op': 'SET_STRATEGY_STATUS',
                                'strategyid': self.__strategyUUID,
                                'status': self.__status
                            }
                        )
                    self.postRecord(params)

            except:
                self.error("An exception occurred during shutdown.")
                traceback.print_exc(file=sys.stdout)
                params = urllib.urlencode(
                        {
                            'op': 'LOG_ENTRY',
                            'msg': "Exception during shutdown: " + traceback.format_exc(),
                            'engine': self.__engine,
                            'strategyid': self.__strategyUUID
                        }
                    )
                self.postRecord(params)

        else:
            self.info("Completed position check actvities, proceeding with shutdown.")
            params = urllib.urlencode(
                    {
                        'op': 'END_STRATEGY_API',
                        'strategyid': self.__strategyUUID,
                        'engine': self.__engine
                    }
                )  
            self.postRecord(params)
            self.stop()

    def forceStop(self):
        self.info("Initiating force stop.")
        params = urllib.urlencode(
                {
                    'op': 'END_STRATEGY_API',
                    'strategyid': self.__strategyUUID,
                    'engine': self.__engine
                }
            )  
        self.postRecord(params)
        self.stop()

    def onFinish(self, bars):
        self.info("Strategy " + self.__strategyUUID + " is finished.")
        self.__status = "ENDED"
        params = urllib.urlencode(
        	    {
                        'op': 'SET_STRATEGY_STATUS',
                        'strategyid': self.__strategyUUID,
                        'status': self.__status
                    }
        	)
        self.postRecord(params)

    #############################################################################################################
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
    #############################################################################################################
    def onBars(self, bars):
        self.info("ON_BARS:")
        diag = True
        self.__barsctr += 1
        self.checkRunTime()
        bar = bars[self.__instrument]
        self.postTradeLog(bar.getClose(), bar.getVolume())

        self.info("#################################")
        if diag:
            self.info("Engine status: %s" % (self.__status))
            if self.__isShuttingDown:
                self.info("isShuttingDown = true")
            else:
                self.info("isShuttingDown = false")
            if self.__position is None:
                self.info("Position is None, no position open.")
            else:
                self.info("Position is open")
                if self.__position.exitActive():
                    self.info("Position is exitActive.")
                    self.info("Exit bid: %s" % self.__exitBid)
                else:
                    self.info("Position is open active.")
            self.info("Price: %s. Volume: %s. Num bars: %s" % (bar.getClose(), bar.getVolume(), self.__barsctr))
            self.info("Cross above: " + str(cross.cross_above(self.__prices, self.__sma)))
            self.info("Cross below: " + str(cross.cross_below(self.__prices, self.__sma)))
            self.info("Price size: " + str(self.__prices.__len__()))
            self.info("Price: " + str(self.__prices.__getitem__(self.__prices.__len__()-1)))
            self.info("SMA Size: " + str(self.__sma.__len__()))
            self.info("SMA: " + str(self.__sma.__getitem__(self.__sma.__len__()-1)))
            self.info("Ask: " + str(self.__ask))
            self.info("Bid: " + str(self.__bid))
        self.info("##################################")

        # Wait until we get the current bid/ask prices.
        if self.__ask is None:
            self.info('self.__ask is None')
            return

        try:
            # If a position was not opened, check if we should enter a long position.
            if self.__position is None and not self.__isShuttingDown:
                if (cross.cross_above(self.__prices, self.__sma) > 0) and (not self.__isExitActive) \
                    and (not self.__isOrderOpenActive):
                    #self.__posSize = random.randint(5, 91)
                    self.info("Entry signal. Enter long limit at %s" % (self.__ask) + ", size=" + str(self.__posSize))
                    self.__position = self.enterLongLimit(self.__instrument, self.__ask, self.__posSize, True)
                    self.__positionsctr_1 += 1
            elif self.__position is None and self.__isShuttingDown: 
                self.info("Position is None and shutdown, stopping strategy.")
                self.stop()
            # Check if we have to close the position
            # getPrice is the fill price of the entry order.
            elif (not self.__position.exitActive()) and (not self.__isExitActive) and (self.__isOrderOpenActive) and \
                (cross.cross_below(self.__prices, self.__sma) > 0):
                if (self.__position.getEntryOrder() is not None) and \
                    (self.__position.getEntryOrder().getExecutionInfo() is not None) and \
                    (self.__position.getEntryOrder().getExecutionInfo().getPrice() < self.__bid):
                    self.info("Exit signal. Sell at %s" % (self.__bid))
                    self.__position.exitLimit(self.__bid)
                    self.__exitBid = self.__bid
                    self.__exitActiveTimer = time.time()
                    self.__isExitActive = True
            else:
                self.info("Finished position evaluation with no actions taken.")

    	except:
            self.info("An exception has occurred during ON BARS.")
            self.info(traceback.print_exc())
            if self.__status != "MIN_TRADE_EXIT_EXCEPTION:":
                if "Trade must be" in traceback.format_exc():
                    self.__status="MIN_TRADE_EXIT_EXCEPTION"

                params = urllib.urlencode(
                    {
                        'op': 'LOG_ENTRY',
                        'msg': "An exception has occurred ON BARS: self.__bid: %s %s " %(self.__bid, traceback.format_exc()),
                        'engine': self.getEngine(),
                        'strategyid': self.getStrategyUUID()
                    }
                )
                self.postRecord(params)
            else:
                self.__status="ERROR"
                params = urllib.urlencode(
                    {
                        'op': 'LOG_ENTRY',
                        'msg': "An exception has occurred ON BARS: self.__bid: %s %s " %(self.__bid, traceback.format_exc()),
                        'engine': self.getEngine(),
                        'strategyid': self.getStrategyUUID()
                    }
                )
                self.postRecord(params)

            pass

def main():

    config = ConfigParser.ConfigParser()
    config.read('bot.cfg')

    # Create BitStamp feed
    barFeed = barfeed.LiveTradeFeed()

    # cash
    # bars = BitStamp live feed
    # fee = 0.5 % per order
    cash = int(config.get('main','cash'))
    brk = broker.PaperTradingBroker(cash, barFeed)

    strat = Strategy(barFeed, brk)

    # Attach the strategy analyzers
    retAnalyzer = returns.Returns()
    strat.attachAnalyzer(retAnalyzer)
    tradesAnalyzer = trades.Trades()
    strat.attachAnalyzer(tradesAnalyzer)
    sharpeRatioAnalyzer = sharpe.SharpeRatio()
    strat.attachAnalyzer(sharpeRatioAnalyzer)
    drawDownAnalyzer = drawdown.DrawDown()
    strat.attachAnalyzer(drawDownAnalyzer)
    
    try:
        strat.run()

        #Cool down
        time.sleep(5)

        # Collect the analysis results
        fin_port_val = strat.getResult()
        cum_ret = retAnalyzer.getCumulativeReturns()[-1] * 100
        stratReturns = tradesAnalyzer.getAllReturns()
        return_avg = stratReturns.mean() * 100
        return_std = stratReturns.std() * 100
        return_min = stratReturns.min() * 100
        return_max = stratReturns.max() * 100
        sharpe_ratio = sharpeRatioAnalyzer.getSharpeRatio(0.05)
        max_drawdown = drawDownAnalyzer.getMaxDrawDown() * 100
        longest_drawdown_duration = drawDownAnalyzer.getLongestDrawDownDuration()

        #fin_port_val = 0
        #cum_ret = 0
        #return_avg = 0
        #return_std = 0
        #return_min = 0
        #return_max = 0
        #sharpe_ratio = 0
        #max_drawdown = 0
        #longest_drawdown_duration = 0

        params = urllib.urlencode(
                {
                    'op': 'LOG_RETURNS',
                    'strategyid': strat.getStrategyUUID(),
                    'fin_port_val': fin_port_val,
                    'cum_returns': cum_ret,
                    'return_avg': return_avg,
                    'return_std': return_std,
                    'return_min': return_min,
                    'return_max': return_max,
                    'sharpe_ratio': sharpe_ratio,
                    'max_drawdown': max_drawdown,
                    'longest_drawdown_duration': longest_drawdown_duration
                }
            )
    
        # Post the returns analysis results
        strat.postRecord(params)

    except:
        strat.info("An exception has occurred during final shutdown.")
        strat.info(traceback.print_exc())
        params = urllib.urlencode(
                    {
                        'op': 'LOG_ENTRY',
                        'msg': "An exception has occurred during final shutdown: " + traceback.format_exc(),
                        'engine': strat.getEngine(),
                        'strategyid': strat.getStrategyUUID()
                    }
                )
        strat.postRecord(params)
        pass

    time.sleep(5)

    command = "sudo /sbin/reboot"
    subprocess.call(command, shell = True)

if __name__ == "__main__":
    main()
