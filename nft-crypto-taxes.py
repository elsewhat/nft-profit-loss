
from requests import Request, Session, HTTPError
import sys
import json
from colorama import init, Fore, Back, Style
from datetime import datetime
from prettytable import PrettyTable, DOUBLE_BORDER 

class WalletNFTHistory: 
    wallet = None
    nfts = {}
    historicEthPrice={}

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
                

                if eventType=='successful':
                    transaction  = Transaction(openseaEvent['transaction']['transaction_hash'],transactionDate,eventType,priceInWei,openseaEvent['quantity'], paymentToken, usdPrice, walletSeller, openseaEvent['winner_account']['address'])
                elif eventType=='transfer':
                    if openseaEvent['transaction']:
                        transactionHash = openseaEvent['transaction']['transaction_hash']
                    else:#Some older transer events have transaction: null
                        transactionHash = openseaEvent['created_date']
                    transaction  = Transaction(transactionHash,transactionDate,eventType,priceInWei,openseaEvent['quantity'], paymentToken, usdPrice, openseaEvent['from_account']['address'], openseaEvent['to_account']['address'])
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
                    # Only apply transfer event if there is no 'successful' (ie. purchase) event
                    if eventType =='successful':
                        if nft.sellTransaction:
                            print("Overwriting existing sell transaction")
                            print(json.dumps(openseaEvent,indent=4)) 
                        nft.sellTransaction = transaction
                    elif eventType =='transfer' and not nft.sellTransaction:
                        nft.sellTransaction = transaction                        
                else:
                    if eventType =='successful':
                        if nft.buyTransaction:
                            print("Overwriting existing sell transaction")
                            print(json.dumps(openseaEvent,indent=4)) 
                        nft.buyTransaction = transaction
                        
                    elif eventType =='transfer' and not nft.buyTransaction:
                        nft.buyTransaction = transaction                    
                
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

        nftsBought = PrettyTable(["NFT name","Bought","Days held","Buy USD","Buy ETH","Break-even ETH"])
        nftsBought.set_style(DOUBLE_BORDER)
        nftsBought.float_format=".2"
        nftsBought.sortby="Buy USD"
        nftsBought.reversesort=True
        nftsBought.align = "l"        

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
            if nft.buyTransaction and nft.sellTransaction:
                nftsTraded.add_row(nft.getTableOutput())
                profits += nft.getProfits()
            elif nft.buyTransaction:
                nftsBought.add_row(nft.getTableOutput())
                totalBuyForUnsold+= nft.buyTransaction.usdPrice
            elif nft.sellTransaction:
                nftsOnlySold.add_row(nft.getTableOutput())
                totalSoldMissingBuy+= nft.sellTransaction.usdPrice
                hasNftsOnlySold=True
        print(nftsTraded)

        print("Profits (USD) {:.2f}".format(profits))
        
        print("Currently holding:")
        print(nftsBought)
        print("Total buy price for unsold nfts {:.2f}".format(totalBuyForUnsold))

        if hasNftsOnlySold:
            print("Missing buy transaction:")
            print("Total sell price where missing buy transaction {:.2f} USD".format(totalSoldMissingBuy))
            print(nftsOnlySold)

class NFT:
    buyTransaction = None
    sellTransaction = None

    def __init__(self, contractAddress,nftName,nftDescription,contractTokenId,openseaLink,imageUrl,imagePreviewUrl):
        self.contractAddress = contractAddress
        self.nftName = nftName
        self.nftDescription = nftDescription
        self.contractTokenId = contractTokenId
        self.openseaLink = openseaLink
        self.imageUrl = imageUrl
        self.imagePreviewUrl = imagePreviewUrl

    def __str__(self):
        if self.buyTransaction and self.sellTransaction:
            return '{}\t{:.2f}\t{:.2f}\t{:.2f}'.format(self.nftName , self.sellTransaction.usdPrice- self.buyTransaction.usdPrice, self.sellTransaction.usdPrice,self.buyTransaction.usdPrice)
        elif self.buyTransaction:
            return '{}\t\t\t{:.2f}'.format(self.nftName,self.buyTransaction.usdPrice)
        elif self.sellTransaction:
            return '{}\t\t{:.2f}\t'.format(self.nftName,self.sellTransaction.usdPrice)

    def getProfits(self):
        if self.buyTransaction and self.sellTransaction and self.sellTransaction.transactionType != 'transfer':
            return self.sellTransaction.usdPrice- self.buyTransaction.usdPrice
        else:
            return 0.0

    def getTableOutput(self):
        if self.buyTransaction and self.sellTransaction:
            profitColor = Back.GREEN
            if self.getProfits()<0:
                profitColor = Back.RED
            elif self.getProfits()==0:
                profitColor = ''

            profitPercentage=0.0
            #Avoid divide by zero in rare cases
            if self.buyTransaction.usdPrice>0.0:
                profitPercentage = ((self.getProfits())/self.buyTransaction.usdPrice)*100
            
            daysHeld =(self.sellTransaction.transactionDate- self.buyTransaction.transactionDate).days

            return [self.nftName,"{}".format(self.buyTransaction.transactionDate.strftime('%Y-%m-%d')),daysHeld,profitColor +'{:.2f}'.format(self.getProfits())+Back.RESET,  profitPercentage,self.sellTransaction.usdPrice,self.buyTransaction.usdPrice]
        elif self.buyTransaction:
            #TODO Avoid hardcoding eth price
            ethPriceNow = 4811.89
            breakEven = self.buyTransaction.usdPrice/ethPriceNow

            daysHeld =(datetime.now()- self.buyTransaction.transactionDate).days

            return [self.nftName,"{}".format(self.buyTransaction.transactionDate.strftime('%Y-%m-%d')),daysHeld,self.buyTransaction.usdPrice, self.buyTransaction.price*1.0e-18, breakEven]
        elif self.sellTransaction:
            return [self.nftName,"{}".format(self.sellTransaction.transactionDate.strftime('%Y-%m-%d')), '', '',self.sellTransaction.usdPrice,'']   

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