import pandas as pd
from datetime import datetime
from decimal import Decimal
import ccxt
import yaml
import json
import time
import h5py
from numpy import nan as NaN

pd.set_option('display.max_rows', 1000)
pd.set_option('expand_frame_repr', False)  # 当列太多时不换行
pd.set_option('display.unicode.ambiguous_as_wide', True)  # 设置命令行输出时的列对齐功能
pd.set_option('display.unicode.east_asian_width', True)
pd.set_option('display.max_columns', 1000)
pd.set_option('display.width', 1000)
pd.set_option('display.max_colwidth', 1000)
pd.set_option('mode.chained_assignment', None)


# 从配置文件中加载各种配置
yaml_path = 'data//settings.yaml'
with open(yaml_path, 'r') as f:
    st = f.read()
    data = yaml.load(st, Loader=yaml.FullLoader)
    f.close()
# 配置信息
default_reduce_rate = data['default_reduce_rate']
pin = data['pin']
test_info = data['test_info']
binance_order_types = data['binance_order_types']
TESTNET_BINANCE_CONFIG = data['TESTNET_BINANCE_CONFIG']
Max_atp = int(data['maximum_number_of_attempts'])
exchange = ccxt.binance(TESTNET_BINANCE_CONFIG)
exchange.set_sandbox_mode(True)
# 变量
strategy_list = ['']
strategy_symbol_list = ['']
strategy_symbol_time_period_list = ['']
reduce_rate_list = ['']


def load_config(strategy, symbol, time_period):
    # 从配置文件中加载各种配置
    with open(yaml_path, 'r') as f:
        global data
        data = f.read()
        data = yaml.load(data, Loader=yaml.FullLoader)
        f.close()
    if {'strategy_list', f'{strategy}_symbol_list', f'{strategy}_{symbol}_time_period_list', f'{strategy}_{symbol}_{time_period}_reduce_rate'}.issubset(data.keys()):
        global strategy_list
        strategy_list = data['strategy_list']
        global strategy_symbol_list
        strategy_symbol_list = [x for x in data.keys() if 'symbol_list' in x]
        global strategy_symbol_time_period_list
        strategy_symbol_time_period_list = [x for x in data.keys() if 'time_period_list' in x]
        global reduce_rate_list
        reduce_rate_list = [x for x in data.keys() if 'reduce_rate' in x].remove('default_reduce_rate')
    else:
        _list = ['strategy_list', f'{strategy}_symbol_list', f'{strategy}_{symbol}_time_period_list', f'{strategy}_{symbol}_{time_period}_reduce_rate']
        with open(yaml_path, 'w') as f:
            for x in _list:
                if x not in data.keys():
                    data[x] = ['']
            yaml.dump(data, f)
            f.close()


def check_signal(strategy, symbol, time_period):
    """
    功能时用于检查每次收到的信号是否在预设文件中，如果没有，则在预设文件中新增，并且在数据库文件中新增对应位置来初始化
    """
    load_config(strategy, symbol, time_period)
    global data
    info = test_info
    with open(yaml_path, 'w') as f:
        if strategy not in data['strategy_list']:
            data['strategy_list'].append(strategy)
            data['strategy_list'] = list(set(data['strategy_list']))
            if '' in data['strategy_list']:
                data['strategy_list'].remove('')
            h = h5py.File(f'data//{strategy}.h5', mode='w')
            h.close()
        if symbol not in data[f'{strategy}_symbol_list']:
            data[f'{strategy}_symbol_list'].append(symbol)
            data[f'{strategy}_symbol_list'] = list(set(data[f'{strategy}_symbol_list']))
            if '' in data[f'{strategy}_symbol_list']:
                data[f'{strategy}_symbol_list'].remove('')
            temp_info = info.copy()
            temp_info['time_period'] = 'none'
            temp_info = pd.DataFrame(temp_info).astype(str)
            temp_info.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a', format='t')
        if time_period not in data[f'{strategy}_{symbol}_time_period_list']:
            data[f'{strategy}_{symbol}_time_period_list'].append(time_period)
            data[f'{strategy}_{symbol}_time_period_list'] = list(set(data[f'{strategy}_{symbol}_time_period_list']))
            if '' in data[f'{strategy}_{symbol}_time_period_list']:
                data[f'{strategy}_{symbol}_time_period_list'].remove('')
            data[f'{strategy}_{symbol}_{time_period}_reduce_rate'] = default_reduce_rate
            if '' in data[f'{strategy}_{symbol}_{time_period}_reduce_rate']:
                data[f'{strategy}_{symbol}_{time_period}_reduce_rate'].remove('')
            df = pd.read_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
            df = pd.DataFrame(df)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            info['time_period'] = time_period
            info['symbol'] = symbol
            info = pd.DataFrame(info)
            info.set_index(['time_period'], inplace=True)
            info = pd.DataFrame(info).astype(str)
            df = df.append(info)
            if 'none' in df.index:
                df = df.drop(['none'])
            df = df[~df.index.duplicated(keep='first')]
            df = df.astype(str)
            df.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
        yaml.dump(data, f)
        f.close()


def schedule_sync():
    """
    定时同步离线资金
    """
    latest_balance = get_latest_balance()
    sync(latest_balance)
    cal_allocated_ratio()


def usdt_future_exchange_info(symbol):
    """
    获取交易币种的最小下单价格、数量精度
    """
    n = 0
    while True:
        try:
            exchange_info = exchange.fapiPublicGetExchangeinfo()
            break
        except Exception:
            time.sleep(1)
            if n >= Max_atp:
                print('If you encounter difficulties, just don\'t do it and get a good night\'s sleep'.center(120))
                raise ccxt.RequestTimeout
            else:
                n += 1
                continue
    # 转化为dataframe
    df = pd.DataFrame(exchange_info['symbols'])
    df = df[['symbol', 'pricePrecision', 'quantityPrecision']]
    df.set_index('symbol', inplace=True)
    price_precision = df.at[symbol, 'pricePrecision']
    quantity_precision = df.at[symbol, 'quantityPrecision']
    # symbol_temp[symbol]['最小下单量精度'] = None if p == 0 else int(p)
    return price_precision, quantity_precision


def get_ticker_price(symbol):
    n = 0
    while True:
        try:
            latest_price = exchange.fapiPublic_get_ticker_price({"symbol": f"{symbol}"})['price']
            break
        except Exception:
            time.sleep(1)
            if n >= Max_atp:
                print('If you encounter difficulties, just don\'t do it and get a good night\'s sleep'.center(120))
                raise ccxt.RequestTimeout
            else:
                n += 1
                continue

    latest_price = Decimal(latest_price)
    return latest_price


def modify_order_quantity(quantity_precision, quantity):
    """
    根据交易所的精度限制（最小下单单位、量等），修改下单的数量和价格
    """
    # 根据每个币种的精度，修改下单数量的精度
    # 获取每个币对的精度
    quantity = Decimal(quantity).quantize(Decimal(quantity_precision))
    return quantity


def get_precision(symbol):
    """
    对接交易所，获取币对的数量和价格精度
    输出 0.000 这样的小数字符串形式
    """
    price_precision, quantity_precision = usdt_future_exchange_info(symbol)
    quantity_precision = '%.0{}f'.format(quantity_precision) % 0
    price_precision = '%.0{}f'.format(price_precision) % 0
    return price_precision, quantity_precision


def modify_decimal(n):
    """
    快速调用的将小数做Decimal处理的小功能
    """
    n = float(n)
    n = Decimal(n).quantize(Decimal("0.000"))
    return n


def get_latest_balance():
    # with open("data//response.json", mode='r') as response:
    #     response = json.load(response)
    #     account_info = response
    n = 0
    while True:
        try:
            response = exchange.fapiPrivateGetAccount()
            break
        except Exception:
            time.sleep(1)
            if n >= Max_atp:
                print('If you encounter difficulties, just don\'t do it and get a good night\'s sleep'.center(120))
                raise ccxt.RequestTimeout
            else:
                n += 1
                continue

    account_info = response

    # 获取账户当前总资金
    assets_df = pd.DataFrame(account_info['assets'])
    assets_df = assets_df.set_index('asset')
    latest_balance = modify_decimal(assets_df.loc['USDT', 'marginBalance'])  # 保证金余额
    return latest_balance


def join(strategy, symbol, time_period):
    """
    当有新交易策略/交易对/交易时间区间出现时使用, 利用原有allocate_ratio来对新加入的部分进行分配
    """
    # 初始化当中, 是以allocate ratio 决定allocate funds
    # 初始化
    L = 0
    df = []
    load_config(strategy, symbol, time_period)
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='r')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            L += len(df.index)
    L = Decimal(L)
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            for t in data[f'{S}_{s}_time_period_list']:
                if {S, s, t}.issubset([strategy, symbol, time_period]):
                    pass
                else:
                    n = df.loc[t, 'period_allocated_ratio']
                    n = modify_decimal(n)
                    n *= modify_decimal((L - Decimal(1)) / L)
                    df.loc[t, 'period_allocated_ratio'] = n
            df = df.astype(str)
            df.to_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
    df = pd.read_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
    df = pd.DataFrame(df).astype(str)
    if 'time_period' in df.columns:
        df.set_index(['time_period'], inplace=True)
    df.loc[time_period, 'schedule_action'] = 'none'
    df.loc[time_period, 'period_allocated_ratio'] = modify_decimal(1 / L)
    df = df.astype(str)
    df.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
    # 编辑好各symbol各period_allocated


def sync(latest_balance):
    """
    属于定时任务, 定期更新最新资金, 使用allocated_ratio来进行分配
    """
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            for t in data[f'{S}_{s}_time_period_list']:
                n = df.loc[t, 'period_allocated_ratio']
                period_allocated_ratio = modify_decimal(n)
                df.loc[t, 'period_allocated_funds'] = modify_decimal(latest_balance * period_allocated_ratio)
            df = df.astype(str)
            df.to_hdf(f'data//{S}.h5', key=f'{s}', mode='a')


def cal_allocated_ratio():
    """
    用于通常情况下的资金分配, 用当前策略的allocated_funds来计算出allocated_ratio
    """
    account_balance = Decimal('0.000')
    symbol_allocated_funds = Decimal('0.000')
    strategy_allocated_funds = Decimal('0.000')
    # 累加出symbol_allocated_funds和strategy_allocated_funds
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            for t in data[f'{S}_{s}_time_period_list']:
                funds = df.loc[t, 'period_allocated_funds']
                funds = modify_decimal(funds)
                symbol_allocated_funds += funds
            strategy_allocated_funds += symbol_allocated_funds
            df = df.astype(str)
            df.to_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
        account_balance += strategy_allocated_funds
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            # 通过allocated_funds来逐个决定_allocated_ratio
            for t in data[f'{S}_{s}_time_period_list']:
                df.loc[t, 'account_balance'] = account_balance
                period_allocated_funds = df.loc[t, 'period_allocated_funds']
                period_allocated_funds = modify_decimal(period_allocated_funds)
                df.loc[t, 'period_allocated_ratio'] = modify_decimal(period_allocated_funds / account_balance)
            df = df.astype(str)
            df.to_hdf(f'data//{S}.h5', key=f'{s}', mode='a')


def remove(strategy, symbol, time_period):
    """
    用于当需要移除交易对的情况, 在配置文件以及数据库文件中都删除其信息
    """
    with open(yaml_path, "w") as f:
        yf = yaml.load(f)
        if 'remove' in strategy:
            strategy = strategy.replace('remove_', '')
            del yf['strategy_list'][f'{strategy}']
            yaml.dump(yf, f)
            yf.close()
            with h5py.File(f'data//{strategy}.h5', "w") as f:
                f.close()
        if 'remove' in symbol:
            symbol = symbol.replace('remove_', '')
            del yf[f'{strategy}_symbol_list'][f'{symbol}']
            yaml.dump(yf, f)
            yf.close()
            with h5py.File(f'data//{strategy}.h5', "a") as f:
                del f[f'{symbol}']
                f.close()
        if 'remove' in time_period:
            symbol = time_period.replace('remove_', '')
            del yf[f'{strategy}_{symbol}_time_period_list'][f'{symbol}']
            yaml.dump(yf, f)
            yf.close()
            df = pd.read_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
            df = pd.DataFrame(df).astype(str)
            del df[f'{time_period}']
            df = df.astype(str)
            df.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
    with open(yaml_path, 'r') as f:
        global data
        data = f.read()
        data = yaml.load(data, Loader=yaml.FullLoader)
        f.close()
    L = 0
    par = Decimal('0.000')
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='r')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            for t in data[f'{S}_{s}_time_period_list']:
                p = df.loc[t, 'period_allocated_ratio']
                p = modify_decimal(p)
                par += p
    for S in data['strategy_list']:
        for s in data[f'{S}_symbol_list']:
            df = pd.read_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
            df = pd.DataFrame(df).astype(str)
            if 'time_period' in df.columns:
                df.set_index(['time_period'], inplace=True)
            for t in data[f'{S}_{s}_time_period_list']:
                n = df.loc[t, 'period_allocated_ratio']
                n = modify_decimal(n)
                n *= modify_decimal(1 / par)
                df.loc[t, 'period_allocated_ratio'] = n
            df = df.astype(str)
            df.to_hdf(f'data//{S}.h5', key=f'{s}', mode='a')
    latest_balance = get_latest_balance()
    sync(latest_balance)
    cal_allocated_ratio()


def update_allocation_statistics(strategy, symbol, time_period):
    """
    通过初始化类别，更新资金分配状况，和计算分配比例
    """
    # ====调用接口====
    # exchange.fapiPrivateGetAccount()
    # with open("data//response.json", mode='r') as response:
    #     response = json.load(response)
    #     account_info = response
    latest_balance = get_latest_balance()
    # ====更新离线数据====
    df = pd.read_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='r')
    df = pd.DataFrame(df).astype(str)
    if 'time_period' in df.columns:
        df.set_index(['time_period'], inplace=True)
    if df.loc[time_period, 'schedule_action'] == 'join':
        join(strategy, symbol, time_period)
        sync(latest_balance)
        cal_allocated_ratio()
    elif df.loc[time_period, 'schedule_action'] == 'sync':
        sync(latest_balance)
        cal_allocated_ratio()
    elif df.loc[time_period, 'schedule_action'] == 'none':
        cal_allocated_ratio()


def position_management(signal_type, strategy, symbol, time_period, quantity, trading_info):
    """
    根据订单类型来来得出开仓量, 和更新数据库文件中的对应记录持仓量
    """
    if signal_type == 'reduce_SHORT':
        # 计算出减仓量
        reduce_rate = data[f'{strategy}_{symbol}_{time_period}_reduce_rate']
        reduce_quantity = Decimal(reduce_rate * quantity)
        quantity = Decimal(quantity - reduce_quantity)
        # 在数据库文件里编辑
        trading_info.loc[time_period, 'period_SHORT_position'] = Decimal(quantity)
    if signal_type == 'reduce_LONG':
        # 计算出减仓量
        reduce_rate = data[f'{strategy}_{symbol}_{time_period}_reduce_rate']
        reduce_quantity = Decimal(reduce_rate * quantity)
        quantity = Decimal(quantity - reduce_quantity)
        # 在数据库文件里编辑
        trading_info.loc[time_period, 'period_LONG_position'] = Decimal(quantity)
    if signal_type == 'open_LONG':
        trading_info.loc[time_period, 'period_LONG_position'] = Decimal(quantity)
    if signal_type == 'open_SHORT':
        trading_info.loc[time_period, 'period_SHORT_position'] = Decimal(quantity)
    if signal_type == 'close_LONG':
        trading_info.loc[time_period, 'period_LONG_position'] = Decimal(0)
    if signal_type == 'close_SHORT':
        trading_info.loc[time_period, 'period_SHORT_position'] = Decimal(0)
    return quantity, trading_info


def processing_trading_action(strategy, symbol, time_period, signal_type):
    """
    处理交易信号，计算开仓量，发送订单
    """
    trading_info = pd.read_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
    trading_info = pd.DataFrame(trading_info).astype(str)
    if 'time_period' in trading_info.columns:
        trading_info.set_index(['time_period'], inplace=True)
    price_precision, quantity_precision = get_precision(symbol)
    latest_price = get_ticker_price(symbol)
    if signal_type == 'reduce_LONG':
        quantity = trading_info.loc[time_period, 'period_LONG_position']
        quantity = modify_order_quantity(quantity_precision, quantity)
        quantity, trading_info = position_management(signal_type, strategy, symbol, time_period, quantity, trading_info)
        if (quantity > Decimal(0)) and ((latest_price * quantity) > 10):
            order = post_order(symbol, signal_type, quantity)
            trading_record(order, strategy, symbol, time_period, signal_type)
            processing_record(strategy, symbol, time_period, signal_type)
        else:
            print('Order quantity is less than $10 or below the precision!'.center(120))
            print('Future Position Did Not Adjust Properly!'.center(120))
    if signal_type == 'reduce_SHORT':
        quantity = trading_info.loc[time_period, 'period_SHORT_position']
        quantity = modify_order_quantity(price_precision, quantity)
        quantity, trading_info = position_management(signal_type, strategy, symbol, time_period, quantity, trading_info)
        if (quantity > Decimal(0)) and ((latest_price * quantity) > 10):
            order = post_order(symbol, signal_type, quantity)
            trading_record(order, strategy, symbol, time_period, signal_type)
            processing_record(strategy, symbol, time_period, signal_type)
        else:
            print('Order quantity is less than $10 or below the precision!'.center(120))
            print('Future Position Did Not Adjust Properly!'.center(120))
    if signal_type == 'open_LONG':
        reduce_quantity = trading_info.loc[time_period, 'period_SHORT_position']
        reduce_quantity = modify_order_quantity(quantity_precision, reduce_quantity)
        reduce_quantity, trading_info = position_management('close_SHORT', strategy, symbol, time_period, reduce_quantity, trading_info)
        if (reduce_quantity > Decimal(0)) and ((latest_price * reduce_quantity) > 10):
            order = post_order(symbol, 'close_SHORT', reduce_quantity)
            trading_record(order, strategy, symbol, time_period, 'close_SHORT')
            processing_record(strategy, symbol, time_period, 'close_SHORT')
        n = trading_info.loc[time_period, 'period_allocated_funds']
        allocated_funds = modify_decimal(n)
        quantity = allocated_funds / latest_price
        quantity = modify_order_quantity(quantity_precision, quantity)
        quantity, trading_info = position_management(signal_type, strategy, symbol, time_period, quantity, trading_info)
        if (quantity > Decimal(0)) and ((latest_price * quantity) > 10):
            order = post_order(symbol, signal_type, quantity)
            trading_record(order, strategy, symbol, time_period, signal_type)
            processing_record(strategy, symbol, time_period, signal_type)
        else:
            print('Order quantity is less than $10 or below the precision!'.center(120))
            print('Future Position Did Not Adjust Properly!'.center(120))
    if signal_type == 'open_SHORT':
        reduce_quantity = trading_info.loc[time_period, 'period_LONG_position']
        reduce_quantity = modify_order_quantity(quantity_precision, reduce_quantity)
        reduce_quantity, trading_info = position_management('close_LONG', strategy, symbol, time_period, reduce_quantity, trading_info)
        if (reduce_quantity > Decimal(0)) and ((latest_price * reduce_quantity) > 10):
            order = post_order(symbol, 'close_LONG', reduce_quantity)
            trading_record(order, strategy, symbol, time_period, 'close_LONG')
            processing_record(strategy, symbol, time_period, 'close_LONG')
        n = trading_info.loc[time_period, 'period_allocated_funds']
        allocated_funds = modify_decimal(n)
        quantity = allocated_funds / latest_price
        quantity = modify_order_quantity(quantity_precision, quantity)
        quantity, trading_info = position_management(signal_type, strategy, symbol, time_period, quantity, trading_info)
        if (quantity > Decimal(0)) and ((latest_price * quantity) > 10):
            order = post_order(symbol, signal_type, quantity)
            trading_record(order, strategy, symbol, time_period, signal_type)
            processing_record(strategy, symbol, time_period, signal_type)
        else:
            print('Order quantity is less than $10 or below the precision!'.center(120))
            print('Future Position Did Not Adjust Properly!'.center(120))
    trading_info = pd.DataFrame(trading_info).astype(str)
    trading_info.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')


def post_order(symbol, signal_type, quantity):
    """
    发送订单, 处理交易所响应
    """
    order = \
        {
            'symbol': symbol,
            'side': binance_order_types[signal_type]['side'],
            'positionSide': binance_order_types[signal_type]['positionSide'],
            'quantity': quantity,
            'type': 'MARKET',
            'newOrderRespType': 'RESULT',
            'timestamp': int(time.time() * 1000)
        }
    order['quantity'] = str(order['quantity'])
    n = 0
    while True:
        try:
            order['timestamp'] = int(time.time() * 1000)
            order = exchange.fapiPrivatePostOrder(order)
            break
        except Exception:
            time.sleep(1)
            if n >= Max_atp:
                print('If you encounter difficulties, just don\'t do it and get a good night\'s sleep'.center(120))
                raise ccxt.RequestTimeout
            else:
                n += 1
                continue
    status = order['status']
    orderId = order['orderId']
    avgPrice = order['avgPrice']
    executedQty = order['executedQty']
    rec01 = f'{status} Order : # {orderId} #'
    rec02 = f'{signal_type} Position {executedQty} at {avgPrice}'
    print('Order_Info'.center(120))
    print(f'{rec01}'.center(120))
    print(f' {rec02}'.center(120))
    return order


def intTodatetime(intValue):
    intValue = int(intValue)
    if len(str(intValue)) == 10:
        # 精确到秒
        timeValue = time.localtime(intValue)
        tempDate = time.strftime("%Y-%m-%d %H:%M:%S", timeValue)
        datetimeValue = datetime.strptime(tempDate, "%Y-%m-%d %H:%M:%S")
    elif 10 < len(str(intValue)) < 15:
        # 精确到毫秒
        k = len(str(intValue)) - 10
        timestamp = datetime.fromtimestamp(intValue / (1 * 10 ** k))
        datetimeValue = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
    else:
        return -1
    return datetimeValue


def trading_record(order, strategy, symbol, time_period, signal_type):
    """
    目前功能暂时用于记录allocated_funds的变化, 通过获取的交易所响应, 计算当前订单的realized_PNL信息
    """
    quantity = order['executedQty']
    price = order['avgPrice']
    order_time = order['updateTime']
    side = signal_type
    order_time = intTodatetime(order_time)
    record = pd.read_csv('data//trading_record.csv')
    record = pd.DataFrame(record).astype(str)
    if 'order_time' in record.columns:
        record['order_time'] = pd.to_datetime(record['order_time'])
        record.set_index('order_time', inplace=True)
    df = \
        {
            'order_time': [f'{order_time}'],
            'strategy': [f'{strategy}'],
            'symbol': [f'{symbol}'],
            'time_period': [f'{time_period}'],
            'side': [f'{side}'],
            'Price': [f'{price}'],
            'quantity': [f'{quantity}']
        }
    df = pd.DataFrame(df)
    if 'order_time' in df.columns:
        df['order_time'] = pd.to_datetime(df['order_time'])
        df.set_index('order_time', inplace=True)
    df = record.append(df)
    df = df.astype(str)
    df.to_csv('data//trading_record.csv')


def processing_record(strategy, symbol, time_period, signal_type):
    """
    通过record来计算PNL和allocated_funds
    """
    df = pd.read_csv('data//trading_record.csv')
    df = pd.DataFrame(df).astype(str)
    if 'order_time' in df.columns:
        df['order_time'] = pd.to_datetime(df['order_time'])
        df.set_index('order_time', inplace=True)
    df_n = df[(df[u'strategy'] == f'{strategy}') & (df[u'symbol'] == f'{symbol}') & (df[u'time_period'] == f'{time_period}')]
    trade_info = pd.read_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
    trade_info = pd.DataFrame(trade_info).astype(str)
    if 'time_period' in trade_info.columns:
        trade_info.set_index(['time_period'], inplace=True)
    if signal_type in ['open_LONG', 'open_SHORT']:
        n_record = dict(df_n.loc[df_n.index[-1]])
        q = n_record['quantity']
        p = n_record['Price']
        n_funds = Decimal(q) * Decimal(p)
        o_funds = trade_info.loc[f'{time_period}', 'period_allocated_funds']
        o_funds = modify_decimal(o_funds)
        funds = (o_funds - n_funds) + n_funds * Decimal('0.9996')
        trade_info.loc[f'{time_period}', 'period_allocated_funds'] = funds
        trade_info = trade_info.astype(str)
        trade_info.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
        df_n.loc[df.index[-1], 'realized_PNL'] = Decimal('0.000')
        df = df.append(df_n)
        df = df[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)
        df = df.astype(str)
        df.to_csv('data//trading_record.csv')
    else:
        if signal_type in ['reduce_SHORT', 'close_SHORT']:
            side_o = 'open_SHORT'
            side = Decimal(1)
            df_o = df[(df[u'side'] == side_o)]
            df_o.sort_index(inplace=True)
        if signal_type in ['reduce_LONG', 'close_LONG']:
            side_o = 'open_LONG'
            side = Decimal(-1)
            df_o = df[(df[u'side'] == side_o)]
            df_o.sort_index(inplace=True)
        if len(df.index) >= 2:
            n_record = df.loc[df.index[-1]]
            o_record = df_o.loc[df_o.index[-1]]
            n_funds = Decimal(n_record['quantity']) * Decimal(n_record['Price']) * Decimal(0.9996)
            o_funds = Decimal(n_record['quantity']) * Decimal(o_record['Price'])
            pnl = (n_funds - o_funds) * side
            n = trade_info.loc[f'{time_period}', 'period_allocated_funds']
            n = modify_decimal(n)
            n += pnl
            trade_info.loc[f'{time_period}', 'period_allocated_funds'] = n
            trade_info = trade_info.astype(str)
            df.loc[df.index[-1], 'realized_PNL'] = pnl
            df = df.astype(str)
            df.to_csv('data//trading_record.csv')
            trade_info.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
        else:
            n_record = df.loc[df.index[-1]]
            n_funds = Decimal(n_record['quantity']) * Decimal(n_record['Price'])
            o_funds = trade_info.loc[f'{time_period}', 'period_allocated_funds']
            o_funds = modify_decimal(o_funds)
            funds = (o_funds - n_funds) + n_funds * Decimal('0.9996')
            n = trade_info.loc[f'{time_period}', 'period_allocated_funds']
            n = modify_decimal(n)
            n *= modify_decimal(funds)
            trade_info.loc[f'{time_period}', 'period_allocated_funds'] = n
            trade_info = trade_info.astype(str)
            trade_info.to_hdf(f'data//{strategy}.h5', key=f'{symbol}', mode='a')
            df.loc[df.index[-1], 'realized_PNL'] = Decimal('0.000')
            for x in df.columns.values.tolist():
                if 'Unnamed' in x:
                    df.drop([x], axis=1, inplace=True)
            df = df.astype(str)
            df.to_csv('data//trading_record.csv')


