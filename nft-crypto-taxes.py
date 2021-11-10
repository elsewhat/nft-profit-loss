
import requests
import sys
import json
from colorama import init, Fore, Back, Style
from datetime import datetime
from prettytable import PrettyTable

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
                asset_id = openseaEvent['asset']['asset_contract']['address'] + '-' + openseaEvent['asset']['token_id']
                

                # payment_token maybe null, so cannot chain easily in python
                payment_token = openseaEvent.get('payment_token')
                if payment_token is not None:
                    #ethereum_usd_price_now = float(payment_token.get('usd_price'))
                    transactionDate = datetime.strptime(openseaEvent['transaction']['timestamp'],'%Y-%m-%dT%H:%M:%S')
                    
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
                    transaction  = Transaction(openseaEvent['transaction']['transaction_hash'],priceInWei,openseaEvent['quantity'], paymentToken, usdPrice, walletSeller, openseaEvent['winner_account']['address'])
                elif eventType=='transfer':
                    if openseaEvent['transaction']:
                        transactionHash = openseaEvent['transaction']['transaction_hash']
                    else:#Some older transer events have transaction: null
                        transactionHash = openseaEvent['created_date']
                    transaction  = Transaction(transactionHash,priceInWei,openseaEvent['quantity'], paymentToken, usdPrice, openseaEvent['from_account']['address'], openseaEvent['to_account']['address'])
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
                        nft.sellTransaction = transaction
                    elif eventType =='transfer' and not nft.sellTransaction:
                        nft.sellTransaction = transaction 
                else:
                    if eventType =='successful':
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
        #print('"NFT name"\tProfit:\tSell price:\tBuy price:')
        nftsTraded = PrettyTable()
        nftsTraded.field_names =["NFT name","Profit","% profit","Sell price","Buy price"]

        nftsBought = PrettyTable()
        nftsBought.field_names=["NFT name","Buy price","Crypto price","Break even"]

        nftsOnlySold = PrettyTable()
        nftsOnlySold.field_names=["NFT name","Profit","% profit","Sell price","Buy price"]

        profits = 0.0
        totalBuyForUnsold=0.0
        totalSoldMissingBuy=0.0
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
        print(nftsTraded)

        print("Profits (USD) {:.2f}".format(profits))

        print("Total buy price for unsold nfts {:.2f}".format(totalBuyForUnsold))
        print("Total sell price where missing buy transaction {:.2f}".format(totalSoldMissingBuy))
        
        print("Currently holding:")
        print(nftsBought)
        print("Missing buy transaction:")
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
        #return  str(self.__class__) + ' - '+ ','.join(('{} = {}'.format(item, self.__dict__[item]) for item in self.__dict__))

    def getProfits(self):
        if self.buyTransaction and self.sellTransaction:
            return self.sellTransaction.usdPrice- self.buyTransaction.usdPrice
        else:
            return 0.0

    def getTableOutput(self):
        if self.buyTransaction and self.sellTransaction:
            profitColor = Back.GREEN
            if self.sellTransaction.usdPrice< self.buyTransaction.usdPrice:
                profitColor = Back.RED
            elif self.sellTransaction.usdPrice== self.buyTransaction.usdPrice:
                profitColor = Back.WHITE

            profitPercentage=100.0
            #Avoid divide by zero in rare cases
            if self.buyTransaction.usdPrice>0.0:
                profitPercentage = ((self.sellTransaction.usdPrice-self.buyTransaction.usdPrice)/self.buyTransaction.usdPrice)*100
            
            return [self.nftName, profitColor +'{:.2f}'.format(self.sellTransaction.usdPrice- self.buyTransaction.usdPrice)+Back.RESET,  '{:.1f}'.format(profitPercentage),'{:.2f}'.format(self.sellTransaction.usdPrice),'{:.2f}'.format(self.buyTransaction.usdPrice)]
        elif self.buyTransaction:
            #nftsBought=[["NFT name","Buy price","Crypto price","Break even"]]
            #TODO Avoid hardcoding eth price
            ethPriceNow = 4811.89
            breakEven = self.buyTransaction.usdPrice/ethPriceNow


            return [self.nftName,'{:.2f}'.format(self.buyTransaction.usdPrice), '{:.2f} {}'.format(self.buyTransaction.price*1.0e-18, self.buyTransaction.paymentToken), '{:.2f} ETH'.format(breakEven)]
        elif self.sellTransaction:
            return [self.nftName, '', '','{:.2f}'.format(self.sellTransaction.usdPrice),'']   

class Transaction:
    def __init__(self, transactionHash,price,quantity,paymentToken, usdPrice, walletSeller, walletBuyer):
        self.transactionHash=transactionHash
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
        while True:
            query = {   'account_address':wallet, 
                'event_type':'successful', 
                #'event_type':'transfer',
                'only_opensea':False,
                #'occured_before':'31.12.2021',  #Needs to be unix epoch style
                #'occured_after':'01.01.2021',
                'offset': offset,
                'limit':300}
            print(query.items())
            response = requests.get('https://api.opensea.io/api/v1/events', params=query,headers=headers)
            response.raise_for_status()

            openseaEvents = response.json()
            if not openseaEvents['asset_events']:
                #No events returned from Opensea API
                break
            else:
                walletNFTHistory.processOpenseaAPIResponse(openseaEvents)
            
            # Additional code will only run if the request is successful
            offset+=300
        offset= 0
        while True:
            query = {   
                'account_address':wallet, 
                'event_type':'transfer',
                'only_opensea':False,
                'offset': offset,
                'limit':300}
            print(query.items())
            response = requests.get('https://api.opensea.io/api/v1/events', params=query,headers=headers)
            response.raise_for_status()

            openseaEvents = response.json()
            if not openseaEvents['asset_events']:
                #No events returned from Opensea API
                break
            else:
                walletNFTHistory.processOpenseaAPIResponse(openseaEvents)
            
            # Additional code will only run if the request is successful
            offset+=300            

        walletNFTHistory.listNFTs()            
    except requests.exceptions.HTTPError as error:
        print(error)
    #


if __name__ == '__main__':
   main()