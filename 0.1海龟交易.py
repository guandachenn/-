## 回测海龟交易法则using python with tqsdk
"""
交易策略：海龟交易法则（20日海龟）
具体：
    1. ATR（真是波动幅度均值） = Max(H-L, H - PDC, PDC - L)
        H: 当日最高价
        L： 当日最低价
        PDC： 前一日收盘价 
    入市策略： 价格超越 20 日突破为基础的短期系统
        只要价格超越20日最高或最低点的一个最小单位，则买入或做空

    止损： 超过或跌破价格的2N时止损
        N  = (19*PDN + TR)/20

    退出： 对于多头头寸系统而言，系统1在价格跌破过去10日最低点时退出。对空头头寸，价格超过10日最高点时退出
"""
#Importing from library
import json
import time
from tqsdk import TqApi, TargetPosTask
from tqsdk.ta import ATR

#The strategy of turtle
class Turtle:
    #Initializing needed data 初始化需要的数据
    def __init__(self, symbol, account = "cgdjustin", donchian_channel_open_position = 20,donchian_channel_stop_profit=10, atr_day_length = 20, max_risk_ratio = 0.5):
        self.account = account #交易账号
        self.symbol = symbol #合约代码
        self.donchian_channel_open_position = donchian_channel_open_position #唐奇安通道的天数周期（买入）
        self.donchian_channel_stop_profit = donchian_channel_stop_profit #唐奇安通道天数周期（止盈）
        self.atr_day_length =  atr_day_length #计算atr的天数
        self.max_risk_ratio = max_risk_ratio  # 最高风险度
        self.state = {
            "position": 0,  # 本策略净持仓数(正数表示多头，负数表示空头，0表示空仓)
            "last_price": float("nan"),  # 上次调仓价
        }
        self.n = 0 #N值
        self.unit = 0 #买卖单位
        self.donchian_channel_high = 0 #唐奇安通道上轨
        self.donchian_channel_low = 0 #唐奇安下轨

        #从库中获取数据
        self.api = TqApi(self.account)  #账号数据
        self.quote = self.api.get_quote(self.symbol)  #行情情况
        kline_length = max(donchian_channel_open_position + 1, donchian_channel_stop_profit + 1, atr_day_length * 5) #k线的根数
        self.klines = self.api.get_kline_serial(self.symbol, 24 * 60 * 60, data_length=kline_length)  #指定合约及周期的K线数据.
        self.account = self.api.get_account()  #获取用户账户资金问题
        self.target_pos = TargetPosTask(self.api, self.symbol)  #创建目标持仓task实例，负责调整归属于该task的持仓 

    
    #交易信号的计算
    def recalc_parameter(self):

        #平均真实波动值 （使用库中的ATR函数，运用kline当成参数，使用需要的数据）
        self.n = ATR(self.klines, self.atr_day_length)

        #计算头寸规模单位 unit = 1% of the account/ 市场的绝对波动幅度
        self.unit = int((self.account.balance * 0.01)/(self.quote.volume_multiple * self.n))

        #唐奇安通道上轨： 前N个交易日的最高价，当价格突破此价格时则买入
        self.donchian_channel_high = max(self.klines.high[-self.donchian_channel_open_position - 1:-1])

        # #唐奇安通道下轨： 前N个交易日的最低价，当价格突破此价格时则做空
        self.donchian_channel_low = min(self.klines.low[-self.donchian_channel_open_position - 1:-1])

        print("唐其安通道上下轨: %f, %f" % (self.donchian_channel_high, self.donchian_channel_low))

        return True

    #设置持仓数
    def set_position(self, pos):
        self.state["position"] = pos
        self.state["last_price"] = self.quote["last_price"]
        self.target_pos.set_target_volume(self.state["position"])

    #入市策略

    
    def try_open(self):
        #开仓策略:入市策略： 价格超越 20 日突破为基础的短期系统.只要价格超越20日最高或最低点的一个最小单位，则买入或做空
        while self.state["position"] == 0 :
            self.api.wait_update()

            # 如果产生新k线,则重新计算唐奇安通道及买卖单位
            if self.api.is_changing(self.klines.iloc[-1],"datetime"):
                self.recalc_parameter
            if self.api.is_changing(self.quote, "last_price"):
                print("最新价: %f" % self.quote.last_price)
                if self.quote.last_price > self.donchian_channel_high:  # 当前价>唐奇安通道上轨，买入1个Unit；(持多仓)
                    print("当前价>唐奇安通道上轨，买入1个Unit(持多仓): %d 手" % self.unit)
                    self.set_position(self.state["position"] + self.unit)
                elif self.quote.last_price < self.donchian_channel_low:  # 当前价<唐奇安通道下轨，卖出1个Unit；(持空仓)
                    print("当前价<唐奇安通道下轨，卖出1个Unit(持空仓): %d 手" % self.unit)
                    self.set_position(self.state["position"] - self.unit)
        
        #交易策略  
        # 退出： 对于多头头寸系统而言，系统1在价格跌破过去10日最低点时退出。对空头头寸，价格超过10日最高点时退出
    def try_close(self):
        while self.state["position"] != 0:
            self.api.wait_update()
            if self.api.is_changing(self.quote,"last_price"):
                print("最新价: ", self.quote.last_price)

                #做多海龟策略
                if self.state["position"] > 0:  #持多单
                    # 加仓策略: 如果是多仓且行情最新价在上一次建仓（或者加仓）的基础上又上涨了0.5N，就再加一个Unit的多仓,并且风险度在设定范围内(以防爆仓)
                    if self.quote.last_price >= self.state["last_price"] + 0.5 * self.n and self.account.risk_ratio <= self.max_risk_ratio:
                        print("加仓:加1个Unit的多仓")
                        self.set_position(self.state["position"] + self.unit)
                    #止损策略： 如果是多仓且行情最新价在上一次建仓的基础下又跌了2N，就卖出全部头寸止损
                    elif self.quote.last_price <= self.state["last_price"] - 2*self.n:
                        print("止损:卖出全部头寸")
                        self.set_position(0)
                    # 止盈策略: 如果是多仓且行情最新价跌破了10日唐奇安通道的下轨，就清空所有头寸结束策略,离场
                    if self.quote.last_price <= min(self.klines.low[-self.donchian_channel_stop_profit - 1:-1]):
                        print("止盈:清空所有头寸结束策略,离场")
                        self.set_position(0)
                
                #做空海龟策略
                elif self.state["position"] < 0:  # 持空单
                    # 加仓策略: 如果是空仓且行情最新价在上一次建仓（或者加仓）的基础上又下跌了0.5N，就再加一个Unit的空仓,并且风险度在设定范围内(以防爆仓)
                    if self.quote.last_price <= self.state["last_price"] - 0.5 * self.n and self.account.risk_ratio <= self.max_risk_ratio:
                        print("加仓:加1个Unit的空仓")
                        self.set_position(self.state["position"] - self.unit)
                    # 止损策略: 如果是空仓且行情最新价在上一次建仓（或者加仓）的基础上又上涨了2N，就平仓止损
                    elif self.quote.last_price >= self.state["last_price"] + 2 * self.n:
                        print("止损:卖出全部头寸")
                        self.set_position(0)
                    # 止盈策略: 如果是空仓且行情最新价升破了10日唐奇安通道的上轨，就清空所有头寸结束策略,离场
                    if self.quote.last_price >= max(self.klines.high[-self.donchian_channel_stop_profit - 1:-1]):
                        print("止盈:清空所有头寸结束策略,离场")
                        self.set_position(0)


    def strategy(sekf):
        """海龟策略"""
        print("等待K线及账户数据...")
        deadline = time.time() + 5
        while not self.recalc_paramter():
            if not self.api.wait_update(deadline=deadline):
                raise Exception("获取数据失败，请确认行情连接正常并已经登录交易账户")
        while True:
            self.try_open()
            self.try_close()


turtle = Turtle("SHFE.hc1901")
print("策略开始运行")
try:
    turtle.state = json.load(open("turtle_state.json", "r"))  # 读取数据: 本策略目标净持仓数,上一次开仓价
except FileNotFoundError:
    pass
print("当前持仓数: %d, 上次调仓价: %f" % (turtle.state["position"], turtle.state["last_price"]))
try:
    turtle.strategy()
finally:
    turtle.api.close()
    json.dump(turtle.state, open("turtle_state.json", "w"))  # 保存数据


"""
一。获取数据
    PDC
    20日内最高价
    20日内最低价
    N（止损价)
    10日最低点
    10日最高点
    ATR 
    当前持仓情况
    tick 
二。交易信号的计算
    买入信号计算

        if tick > 十五日价格最高点：
            买入（价格，下单方式，头寸）
    头寸计算
    卖出信号计算
    止损信号计算

三。下单部分
    开仓部分
        买开
        卖开
    平仓部分
        买平
        卖平
        止损平
"""

