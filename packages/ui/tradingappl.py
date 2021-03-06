'''
Created on 20 Feb 2018

@author: adil
'''


import sys
import re
import datetime
import bisect


from ui.abstractapp import Application
from ui.clientmanager import ClientManager

from server import price
from server.dataunavailable import DataUnavailableEx

from trades.transaction import Transaction, TransactionError
from trades.order import Order, OrderStatus
from trades.order import TransType
from trades.PositionException import PositionException
from trades.client import ClientException
from trades.security import Security
from ui.securitymanager import SecurityManager
from server.orderbroker import OrderBroker


import pandas as pd



class SymbolDoesNotExistError(Exception):
    """
        Symbol not listed in stock exchange
    """
    
class TradingApplication(Application):
    '''
    Trading Application Class, a singleton for selling and buying securities
    '''

    instance = None

    @staticmethod
    def getInstance():
        if not TradingApplication.instance :
            TradingApplication.instance = TradingApplication( 
                                                Application.getTransactiosFileName() )
            
        return TradingApplication.instance
    
    def __init__(self, transactions_file_name):
        '''
        Constructor
        '''
        self.transactions_file_name = transactions_file_name
        self.security = SecurityManager.getInstance()

        
        self.transactions = {}
        
        with open(self.transactions_file_name, "r") as transactions_file :
            for line in transactions_file :
                line = line.rstrip()
                
                (trans_date, clt_id, tran_type, symbol, price, qty) = line.split("|")
                transaction = Transaction()
                transaction.clientID = int(clt_id)
                transaction.date = datetime.datetime.strptime(trans_date, Transaction.DATE_FORMAT)  #Convert to date object
                transaction.trans_type = TransType(int(tran_type))
                transaction.symbol = symbol
                transaction.price = float(price)
                transaction.quantity = int(qty)
                self.transactions[transaction.date] = transaction
    
              
    #Helper function implementing an efficient algorithm to return all transactions between two dates
    #The function returns a list of all found transactions Order ( nlog(N) )
    def _transactions_between(self, from_date, to_date):
        
        #First get a sorted list of all transactions dict keys (transaction dates)
        date_list = sorted(self.transactions.keys())
        
        #Then get location of first transaction on the from_date
        begin = bisect.bisect_left(date_list, from_date)
        
        #And location of first transaction on the day after the to_date
        end = bisect.bisect_right(date_list, to_date + datetime.timedelta(days=1))
        
        if begin != len(date_list) : #check that there are transactions on or after the from_date
            
            #Build a list of transactions using comprehension 
            #by using items in date_list from begin - end, 
            #as keys to the transactions dictionary
            return [ self.transactions[key] for key in date_list[begin:end] ]
    
    
    def saveTransactions(self):
        with open(self.transactions_file_name, "w") as trans_file :
            for trans_date in sorted(self.transactions.keys()) :
                trans_file.write(str(self.transactions[trans_date]) + "\n")            
                
                
    def sell(self, client, symbol):
        if self.security.checkSecurityBySymbol(symbol) and client.hasPosition(symbol) :
            try:
                max_qty = client.getPosition(symbol).getQuantity()
                #current market value
                current_value = float(self.security.getCurrentMarketValue(symbol))   
                     
                print("You can sell a maximum of %d" % max_qty)
                quantity = int(self._promptForQuantity())
                max_price = quantity * current_value
                if quantity <= max_qty : 
                    print("You asked to sell %d stocks of %s, which is now trading at %s, maximum price is %s" % 
                                    (quantity, symbol, current_value, max_price)
                          )
                    
                    ask_price = float(self._promptForPrice())
                    
                        
                    sell_order = Order(int(client.getID()), symbol, TransType.SELL, quantity, ask_price)
                    
                    #if ask price <= current market value the sell order will be executed
                    if ask_price <= max_price:
                        response = input("Are you happy to submit your order [y/n]? ")
                        if re.search(r"^[Yy]", response):
                            transaction = OrderBroker().executeOrder(sell_order)  
                            if transaction :
                                transaction.commit()
                                self.transactions[transaction.date] = transaction
                            else:
                                raise TransactionError("Sell order failed")
                        
                        else:
                            #if response="no"
                            sell_order.setStatus(OrderStatus.KILLED)         
                    else:
                        #if ask_price > current_valu sell order will be killed
                        print("Order cannot be executed; the maximum sell price for %d security/s is %s" %(quantity,max_price)) 
                        sell_order.setStatus(OrderStatus.KILLED)
                else:    
                    print("Order cannot be executed; you don't have enough stock")
                    return
            
            except TypeError as ex :
                print ("Exception: %s " %ex, file = sys.stderr)
                
        else :
            raise SymbolDoesNotExistError("Cannot find symbol") 
                  
    def buy(self, client, symbol):
        if self.security.checkSecurityBySymbol(symbol) :
            try:
                quantity = int(self._promptForQuantity())
                current_value = float(self.security.getCurrentMarketValue(symbol))
                min_price = quantity * current_value
                print("You asked to buy %d stocks of %s, which is now trading at %s, minimum price will be %s" % 
                                (quantity, symbol,current_value, min_price)
                      )
                ask_price = float(self._promptForPrice())
                #current market value
               
                buy_order = Order(int(client.getID()), symbol, TransType.BUY, quantity, ask_price)
                
                
               
                #if ask price >= current market value the buy order will be executed
                if ask_price >= min_price:
                    
                    response = input("Are you happy to submit your order [y/n]? ")
                    if re.search(r"^[Yy]", response):
                        transaction = OrderBroker().executeOrder(buy_order)
                        if transaction :
                            transaction.commit()
                            self.transactions[transaction.date] = transaction
                        else :
                            raise TransactionError("Buy order failed")
                    else :
                        #if response="no"
                        buy_order.setStatus(OrderStatus.KILLED)
                else:
                    #if ask_price < current_valu buy order will be killed
                    print("Order cannot be executed; the minimum buy price for %d security/s is %s" %(quantity,min_price))
                    buy_order.setStatus(OrderStatus.KILLED)
                     
                
            except TypeError as ex :
                print ("Exception: %s " %ex, file = sys.stderr)
        
        
        else :
            raise SymbolDoesNotExistError("Cannot find symbol")
    
    
    def listAllTransactions(self):
        print("""
Date & time of transaction  =>     Transaction Details
===========================   ============================================================""")
        for date, transaction in self.transactions.items() :
            print(date, " => ", transaction)
            print("""
===========================   ============================================================""")
    
    
    def listTransactionsPerClient(self, client):
        
        response = input("Listing transactions for client %s? [y/n] " % client.getName() )
        if not re.search(r"^[Yy]", response):
            return
        
        clientTransSet= pd.read_csv(self.transactions_file_name,delimiter="|", header=None,
                    names=["Date_Time","ID","Type","Symbol","Price","Quantity"],index_col="Date_Time")
        
        select_data=clientTransSet.loc[clientTransSet.ID == client.getID(),:]
        print("""
 Date & time of transaction  =>      Transaction Details
===========================   ========================================""")
        print(select_data)
        print("""
===========================   ========================================""")
     
    
    #Lists all transactions between two dates (inclusive); 
    #pass two dates of equal value to list transactions on a particular date
    def listTransactionsInPeriod(self, from_date, to_date):
        try :
            trns_in_dates = self._transactions_between(from_date, to_date)
            
            if trns_in_dates :
                print("""
Date & time of transaction  =>     Transaction Details
===========================   ========================================""")
                 
                for transaction in trns_in_dates :
                   
                    print(transaction)   
                    
                    
                    print("""
===========================   ========================================""")
     
                
            else :
                print("No transaction found on this period!")
        except Exception as ex:
            print("Exception: %s" % ex, file=sys.stderr)
            
#        Old inefficient implementation (order O(n))
#         for transaction in self.transactions.values() :
#             if transaction.get_date().date() >= from_date.date() and 
#                transaction.get_date().date() <= to_date.date()  :
#
#                 print(transaction)    
    
    def listTransactionsPerSecurity(self, symbol):
        if not self.security.checkSecurityBySymbol(symbol):
            raise SymbolDoesNotExistError("Cannot find symbol")
        
        print("Listing transactions for Security %s" % symbol )
        
        print("""
Date & time of transaction  =>     Transaction Details
===========================   ========================================""")
                 

        for transaction in self.transactions.values() :
            if transaction.get_symbol() == symbol :
                print(transaction)
        
                print("""
===========================   ========================================""")
     
    
    def _menu(self):
        print("""Client's Manager Menu
            Please choose an option: 
            1:    Buy securities.
            2:    Sell securities.
            3:    Query a security's price.
            4:    List transactions for a client.
            5:    List transactions in date.
            6:    List transactions in a two-dates period
            7:    List transactions in security
            8:    List all recorded transactions
            0:    Return to Main Menu
            """)
        try :
            return int(input("Enter your choice: "))
        except ValueError :
            return ""
        
        
    def _menu0(self):       #Return to Main
        pass
    
    
    def _menu1(self):       #Buy
        
        try:
            client_id = self._promptForID()
            client = ClientManager.getInstance().retrieveClient(client_id)
            print("Hello %s, you asked to buy some stocks." % 
                    client.getName()
                  )
            symbol = self._promptForSymbol()
            self.buy(client, symbol) 
            
        except (TransactionError, SymbolDoesNotExistError) as  ex :
            print("Exception: ", ex, ex.__doc__, file = sys.stderr)
    
    def _menu2(self):       #Sell
        
        try:
            client_id = self._promptForID()
            client = ClientManager.getInstance().retrieveClient(client_id)
            print("Hello %s, you asked to sell some stocks." % client.getName())
            
            symbol = self._promptForSymbol()
            
            if client.hasPosition(symbol) :
                self.sell(client, symbol) 
            else :
                print ("You don't hold a position on %s, and we don't currently support sell short" % symbol)
            
        except (TransactionError, SymbolDoesNotExistError) as  ex :
            print("Exception: ", ex, ex.__doc__, file = sys.stderr)
  
    
    def _menu3(self):       #Query price
        symbolValue = self._promptForSymbol()
        price = self.security.getCurrentMarketValue(symbolValue)
        print("Last recorded price for this particular security is %s" %(price))
        
        
    def _menu4(self):   #List transactions for a client.
        try:
            client_id = self._promptForID()
            client = ClientManager.getInstance().retrieveClient(client_id)
            self.listTransactionsPerClient(client)
            
        except ClientException as  ex :
            print("Exception: ", ex, ex.__doc__, file = sys.stderr)  
        
    def _menu5(self):   #List transactions in date.
        try:
            date_str = input("Enter transaction date using format: YYYY-MM-DD:")
            date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            self.listTransactionsInPeriod(date, date)
        except Exception as ex:
            print("Exception: ", ex, ex.__doc__, file = sys.stderr)  
    
    def _menu6(self):   #List transactions in a period
        
        try:
            date_str = input("Enter first transaction date using format: YYYY-MM-DD:")
            from_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            date_str = input("Enter second transaction date using format: YYYY-MM-DD:")
            to_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            
            if from_date <= to_date :
                self.listTransactionsInPeriod(from_date, to_date)
            else :
                print("Fist date cannot be after second date!")
                
        except Exception as ex:
            print("Exception: ", ex, ex.__doc__, file = sys.stderr)  
    
    def _menu7(self):   #List transactions per security
        
        try :
            symbol = self._promptForSymbol()
            self.listTransactionsPerSecurity(symbol)
        except Exception as ex:
            print("Exception: ", ex, ex.__doc__, file = sys.stderr)  
        
    
    def _menu8(self):       #List all transactions
        self.listAllTransactions()
    
    def _menu9(self):       #List all Securities
        self.security.listSecurities()
                                  
    def run(self):
            menu_items = [
                            self._menu0, self._menu1, self._menu2, 
                            self._menu3, self._menu4, self._menu5, 
                            self._menu6, self._menu7, self._menu8, 
                            self._menu9
                          ]
            try:
                choice = self._menu()
                if choice in range(0,10) :
                    menu_item = menu_items[choice]
                    menu_item()
                else :
                    print ("Error: Undefined input ", file=sys.stderr)
                    
            except (ClientException, PositionException, DataUnavailableEx) as ex :
                print("Exception: ", ex, file=sys.stderr)