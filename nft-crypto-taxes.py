
from requests import Request, Session, HTTPError
import sys
import copy
import json
from colorama import init, Fore, Back, Style
from datetime import datetime
from prettytable import PrettyTable, DOUBLE_BORDER 

class WalletNFTHistory: 
    wallet = None
    nfts = {}
    historicEthPrice={}
    REPORT_PROFIT=1
    REPORT_HOLDING=2
    REPORT_ONLY_SOLD=3

    def __init__(self, wallet,historicEthPrice):
        self.wallet = wallet
        self.historicEthPrice = historicEthPrice
    
    # Process the opensea response events
    def processOpenseaAPIResponse(self, openseaEvents):
        
        #debug only
        #print(json.dumps(openseaEvents,indent=4))
        
        # Process all events from the API
        # Each transaction will either create a new NFT object or add a buy/sell transaction to an existing NFT
        for openseaEvent in openseaEvents['asset_events']:
            try:
                eventType = openseaEvent['event_type']

                #id of asset
                if not openseaEvent['asset'] and openseaEvent['asset_bundle']:
                    print("Bundles from OpenSea are currently not supported. Skipped bundle \"{}\"".format(openseaEvent['asset_bundle']['name'] ))
                    continue

                asset_id = openseaEvent['asset']['asset_contract']['address'] + '-' + openseaEvent['asset']['token_id']
                

                transactionDate = datetime.strptime(openseaEvent['transaction']['timestamp'],'%Y-%m-%dT%H:%M:%S')

                if eventType=='successful':
                    #ethereum_usd_price_now = float(payment_token.get('usd_price'))
                    
                    payment_token = openseaEvent.get('payment_token')
                    #Lookup eth price from dictionary (key is 'yyyy-mm-dd')
                    ethpriceAtTransaction = self.historicEthPrice[transactionDate.strftime('%Y-%m-%d')]
                    priceInWei = float(openseaEvent['total_price'])
                    paymentToken = payment_token.get('symbol')
                    usdPrice = (priceInWei*1.0e-18)*ethpriceAtTransaction
                else:
                    priceInWei=0
                    usdPrice=0.0
                    paymentToken=None

                #seller may be in rare cases be null, so cannot chain easily
                walletSeller = openseaEvent['seller']
                if walletSeller is not None:
                    walletSeller = walletSeller['address']
                
                isTransferEvent = False
                if eventType=='successful':
                    transaction  = Transaction(openseaEvent['transaction']['transaction_hash'],transactionDate,eventType,priceInWei,openseaEvent['quantity'], paymentToken, usdPrice, walletSeller, openseaEvent['winner_account']['address'])
                elif eventType=='transfer':
                    isTransferEvent=True
                    if openseaEvent['transaction']:
                        transactionHash = openseaEvent['transaction']['transaction_hash']
                    else:#Some older transer events have transaction: null
                        transactionHash = openseaEvent['created_date']
                    transaction  = Transaction(transactionHash,transactionDate,eventType,priceInWei,openseaEvent['quantity'], paymentToken, usdPrice, openseaEvent['from_account']['address'], openseaEvent['to_account']['address'])
                else:
                    print("Unsupported event {}".format(eventType))
                    raise
                #print(transaction)

                # Create new NFT or add transaction to existing NFT
                if asset_id not in self.nfts:
                    nftName = openseaEvent['asset']['name']
                    #Some asset names are None, so use collection in these cases to set name
                    if not nftName:
                        nftName = openseaEvent['asset']['collection']['name'] + ' #' + openseaEvent['asset']['token_id']

                    nft  = NFT(openseaEvent['asset']['asset_contract']['address'] ,nftName,openseaEvent['asset']['description'],openseaEvent['asset']['token_id'],openseaEvent['asset']['permalink'],openseaEvent['asset']['image_url'],openseaEvent['asset']['image_preview_url'],)   
                else:
                    #print('Add transaction to existing NFT')
                    nft = self.nfts.get(asset_id)
                

                if transaction.isSeller(self.wallet):
                    nft.addSellTransaction(copy.copy(transaction),isTransferEvent)                  
                else:
                    nft.addBuyTransaction(copy.copy(transaction),isTransferEvent)   
                 
                
                self.nfts[asset_id]= nft
            except BaseException as ex:
                print("Failed parsing transaction")
                print(ex)
                print(json.dumps(openseaEvent,indent=4))
                raise
        

    def listNFTs(self):
        
        #NFTs with both buy and sold transaction
        print("NFT profits:")
        #Table setup ref https://pypi.org/project/prettytable/
        nftsTraded = PrettyTable(["NFT name","Bought","Days held","Profit USD","% profit","Sell USD","Buy USD"])
        nftsTraded.set_style(DOUBLE_BORDER)
        nftsTraded.float_format=".2"
        nftsTraded.sortby="Sell USD"
        nftsTraded.reversesort=True
        nftsTraded.align = "l"

        nftsHolding = PrettyTable(["NFT name","Bought","Days held","Buy USD","Buy ETH","Break-even ETH"])
        nftsHolding.set_style(DOUBLE_BORDER)
        nftsHolding.float_format=".2"
        nftsHolding.sortby="Buy USD"
        nftsHolding.reversesort=True
        nftsHolding.align = "l"        

        nftsOnlySold = PrettyTable(["NFT name","Sold","Profit","% profit","Sell USD","Buy USD"])
        nftsOnlySold.set_style(DOUBLE_BORDER)
        nftsOnlySold.float_format=".2"
        nftsOnlySold.sortby="Sell USD"
        nftsOnlySold.reversesort=True  
        nftsOnlySold.align = "l"          

        profits = 0.0
        totalBuyForUnsold=0.0
        totalSoldMissingBuy=0.0
        hasNftsOnlySold=False
        for nftKey in self.nfts:
            nft = self.nfts[nftKey]
            nft.addToReport(nftsTraded,self.REPORT_PROFIT)
            nft.addToReport(nftsHolding,self.REPORT_HOLDING)
            nft.addToReport(nftsOnlySold,self.REPORT_ONLY_SOLD)

        print(nftsTraded)

        #print("Profits (USD) {:.2f}".format(profits))
        
        print("Currently holding:")
        print(nftsHolding)
        #print("Total buy price for unsold nfts {:.2f}".format(totalBuyForUnsold))

        if hasNftsOnlySold:
            print("Missing buy transaction:")
            #print("Total sell price where missing buy transaction {:.2f} USD".format(totalSoldMissingBuy))
            print(nftsOnlySold)

class NFT:
    def __init__(self, contractAddress,nftName,nftDescription,contractTokenId,openseaLink,imageUrl,imagePreviewUrl):
        self.contractAddress = contractAddress
        self.nftName = nftName
        self.nftDescription = nftDescription
        self.contractTokenId = contractTokenId
        self.openseaLink = openseaLink
        self.imageUrl = imageUrl
        self.imagePreviewUrl = imagePreviewUrl
        #Array of tuples of (buyTransaction, sellTransaction)
        self.__walletTransactions=[(None,None)]

    def __str__(self):
        buyTransaction,sellTransaction = self.__walletTransactions[0]

        if buyTransaction and sellTransaction:
            return '{}\t{:.2f}\t{:.2f}\t{:.2f}'.format(self.nftName , sellTransaction.usdPrice- buyTransaction.usdPrice, sellTransaction.usdPrice,buyTransaction.usdPrice)
        elif buyTransaction:
            return '{}\t\t\t{:.2f}'.format(self.nftName,buyTransaction.usdPrice)
        elif sellTransaction:
            return '{}\t\t{:.2f}\t'.format(self.nftName,sellTransaction.usdPrice)

    def getProfits(self):
        profits = 0.0
        for walletTransaction in self.__walletTransactions: 
            buyTransaction,sellTransaction = walletTransaction

            # Only add to profits if both buy and sell transaction have a usdPrice
            if buyTransaction and sellTransaction and sellTransaction.transactionType != 'transfer':
                profits+= sellTransaction.usdPrice- buyTransaction.usdPrice

        return profits
 
    def addBuyTransaction(self, transaction, isTransferEvent):
        existingBuyTransaction,existingSellTransaction = self.__walletTransactions[0]

        if not isTransferEvent:
            for index, walletTransaction in enumerate(self.__walletTransactions):
                #print("Creating new buy transaction for {}".format(self.nftName))
                currentBuyTransaction,currentSellTransaction = walletTransaction
                if currentBuyTransaction == None:
                    if index > 0:
                        print("Adding additional buy for {}".format(self.nftName))
                    self.__walletTransactions[index]=(transaction,currentSellTransaction)
                    return
        elif isTransferEvent==True and not existingBuyTransaction:
            #self.__buyTransaction = transaction   
            self.__walletTransactions[0] = (transaction,existingSellTransaction)
    
    def addSellTransaction(self, transaction, isTransferEvent):
        existingBuyTransaction,existingSellTransaction = self.__walletTransactions[0]

        #Check if we've owned this NFT more than once
        # if last entry in __walletTransactions already has a sellTransaction, add a new entry
        if not isTransferEvent:
            _,lastSellTransaction = self.__walletTransactions[len(self.__walletTransactions)-1]
            if lastSellTransaction!= None:
                print("Creating new sell transaction for {}".format(self.nftName))
                self.__walletTransactions.append((None,transaction))
                return       

        if isTransferEvent==False:
            #self.__sellTransaction = transaction
            self.__walletTransactions[0] = (existingBuyTransaction,transaction)
        elif isTransferEvent==True and not existingSellTransaction:
            #self.__sellTransaction = transaction
            self.__walletTransactions[0] = (existingBuyTransaction,transaction)


    def addToReport(self,prettyTableForReport, reportType):
        buyTransaction,sellTransaction = self.__walletTransactions[0]

        if reportType == WalletNFTHistory.REPORT_PROFIT:
            if buyTransaction and sellTransaction:    
                prettyTableForReport.add_row(self.getTableOutput())
        elif reportType == WalletNFTHistory.REPORT_HOLDING:
            if buyTransaction and not sellTransaction:
                prettyTableForReport.add_row(self.getTableOutput())
        elif reportType == WalletNFTHistory.REPORT_ONLY_SOLD:      
            if sellTransaction and not buyTransaction:
               prettyTableForReport.add_row(self.getTableOutput()) 
        else:
            print("Unsupported report type {}".format(reportType))      

    def getTableOutput(self):
        buyTransaction,sellTransaction = self.__walletTransactions[0]

        if buyTransaction and sellTransaction:
            profitColor = Back.GREEN
            profits = self.getProfits()
            if profits<0:
                profitColor = Back.RED
            elif profits==0:
                profitColor = ''

            totalSellUSD=0.0
            totalBuyUSD=0.0
            countSold = 0
            daysHeld=0
            #Sum together for multiple sales
            for walletTransaction in self.__walletTransactions: 
                buyTransaction,sellTransaction = walletTransaction
                if buyTransaction and sellTransaction and sellTransaction.transactionType != 'transfer':
                    totalBuyUSD += buyTransaction.usdPrice
                    totalSellUSD += sellTransaction.usdPrice
                    countSold+=1
                    if daysHeld ==0:
                        daysHeld =(sellTransaction.transactionDate- buyTransaction.transactionDate).days
                    else:
                        #Quasi average
                        daysHeld = ((sellTransaction.transactionDate- buyTransaction.transactionDate).days + daysHeld)/2

            profitPercentage=0.0
            #Avoid divide by zero in rare cases
            if totalBuyUSD >0.0:
                profitPercentage = ((profits)/totalBuyUSD)*100

            nftName = self.nftName
            if countSold >1:
                nftName += 'x{}'.format(countSold)

            return [nftName,"{}".format(buyTransaction.transactionDate.strftime('%Y-%m-%d')),daysHeld,profitColor +'{:.2f}'.format(profits)+Back.RESET,  profitPercentage,totalSellUSD,totalBuyUSD]
        elif buyTransaction:
            #TODO Avoid hardcoding eth price
            ethPriceNow = 4811.89
            breakEven = buyTransaction.usdPrice/ethPriceNow

            daysHeld =(datetime.now()- buyTransaction.transactionDate).days

            return [self.nftName,"{}".format(buyTransaction.transactionDate.strftime('%Y-%m-%d')),daysHeld,buyTransaction.usdPrice, buyTransaction.price*1.0e-18, breakEven]
        elif sellTransaction:
            return [self.nftName,"{}".format(sellTransaction.transactionDate.strftime('%Y-%m-%d')), '', '',sellTransaction.usdPrice,'']   

class Transaction:
    def __init__(self, transactionHash,transactionDate,transactionType, price,quantity,paymentToken, usdPrice, walletSeller, walletBuyer):
        self.transactionHash=transactionHash
        self.transactionDate=transactionDate
        self.transactionType=transactionType
        self.price = price
        self.quantity = quantity
        self.paymentToken=paymentToken
        self.usdPrice=usdPrice
        self.walletSeller=walletSeller
        self.walletBuyer= walletBuyer

    def isSeller(self,wallet):
        if self.walletSeller==wallet:
            return True
        else: 
            return False

    def isBuyer(self,wallet):
        if self.walletBuyer==wallet:
            return True
        else: 
            return False

    

    def __str__(self):
        return  'Transaction: '+ ','.join(('{} = {}'.format(item, self.__dict__[item]) for item in self.__dict__))                        

# Parse ethprice.csv into a dict object 
def getHistoricEthPrice():
    historicEthPrice = {}
    with open('ethprice.csv', 'r') as file:
        for line in file:
            line = line.rstrip()
            priceDate = line.split(",")[0]
            ethPrice = float(line.split(",")[1])
            historicEthPrice[priceDate]=ethPrice

    return historicEthPrice


def main():
    wallet = sys.argv[1]
    #openseaAPIKey = sys.argv[1]

    # Parse ethprice.csv into a dict object 
    historicEthPrice = getHistoricEthPrice()

    walletNFTHistory = WalletNFTHistory(wallet,historicEthPrice)


    query = {   'account_address':wallet, 
                'event_type':'successful', 
                #'event_type':'transfer',
                'only_opensea':False,
                #'occured_before':'31.12.2021',  #Needs to be unix epoch style
                #'occured_after':'01.01.2021',
                'offset': 0,
                'limit':300}

    headers = { #'X-API-KEY': 'xxx',
                'Accepts':'application/json'}      
    #print(query)
    try:
        offset=0
        httpOpenSeaSession = Session()
        while True:
            query = {   
                'account_address': wallet, 
                'event_type': 'successful', 
                'only_opensea': False,
                'offset': offset,
                'limit': 300}

            httpRequest = Request('GET','https://api.opensea.io/api/v1/events', params=query,headers=headers)
            httpRequest = httpRequest.prepare()
            print("REQUEST: {}".format(httpRequest.url))
            response = httpOpenSeaSession.send(httpRequest)

            response.raise_for_status()

            openseaEvents = response.json()
            if not openseaEvents['asset_events']:
                #No events returned from Opensea API indicating no more pages
                break
            elif offset+300 > 10000:
                print("WARNING: OpenSea API does not currently support more than 10 000 events. Skipping remaining ones")
                break            
            else:
                walletNFTHistory.processOpenseaAPIResponse(openseaEvents)
            
            # Additional code will only run if the request is successful
            offset+=300
        offset= 0
        while True:
            query = {   
                'account_address': wallet, 
                'event_type': 'transfer',
                'only_opensea': False,
                'offset': offset,
                'limit': 300}
            httpRequest = Request('GET','https://api.opensea.io/api/v1/events', params=query,headers=headers)
            httpRequest = httpRequest.prepare()
            print("REQUEST: {}".format(httpRequest.url))
            response = httpOpenSeaSession.send(httpRequest)

            response.raise_for_status()

            openseaEvents = response.json()
            if not openseaEvents['asset_events']:
                #No events returned from Opensea API indicating no more pages
                break
            elif offset+300 > 10000:
                print("WARNING: OpenSea API does not currently support more than 10 000 events. Skipping remaining ones")
                break
            else:
                walletNFTHistory.processOpenseaAPIResponse(openseaEvents)
            
            # Additional code will only run if the request is successful
            offset+=300            

        walletNFTHistory.listNFTs()            
    except HTTPError as error:
        print(error)
        print(json.dumps(error.response.json()),indent=4)
    #


if __name__ == '__main__':
   main()