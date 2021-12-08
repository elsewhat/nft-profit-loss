
from requests import Request, Session, HTTPError
import requests
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
                    print("WARNING: Bundles from OpenSea are currently not supported. Skipped bundle \"{}\"".format(openseaEvent['asset_bundle']['name'] ))
                    continue

                asset_id = openseaEvent['asset']['asset_contract']['address'] + '-' + openseaEvent['asset']['token_id']
                
                if openseaEvent['transaction'] and openseaEvent['transaction']['timestamp']:
                    transactionDate = datetime.strptime(openseaEvent['transaction']['timestamp'],'%Y-%m-%dT%H:%M:%S')
                else:
                    print("WARNING: transaction.timestamp is null for {} ".format(asset_id) + " Using created_date instead which may cause some issues with days held calculation.")
                    transactionDate = datetime.strptime(openseaEvent['created_date'],'%Y-%m-%dT%H:%M:%S.%f')

                if eventType=='successful':
                    #ethereum_usd_price_now = float(payment_token.get('usd_price'))
                    
                    payment_token = openseaEvent.get('payment_token')
                    #Lookup eth price from dictionary (key is 'yyyy-mm-dd')
                    transactionYYYYMMDD = transactionDate.strftime('%Y-%m-%d')
                    if transactionYYYYMMDD in self.historicEthPrice:
                        ethpriceAtTransaction = self.historicEthPrice[transactionYYYYMMDD]
                    else:
                        # Dict keys are ordered ref https://stackoverflow.com/a/16125237/250787 so safe to do this
                        keyLastDate = list(self.historicEthPrice.keys())[-1]
                        ethpriceAtTransaction = self.historicEthPrice[keyLastDate]
                        print("WARNING: ethprice.csv does not contain a value for {}. Using value {:.2f} for {} instead.".format(transactionYYYYMMDD,ethpriceAtTransaction,keyLastDate) )

                    priceInWei = float(openseaEvent['total_price'])
                    priceInETH = priceInWei*1.0e-18
                    paymentToken = payment_token.get('symbol')
                    usdPrice = priceInETH*ethpriceAtTransaction
                else:
                    priceInWei=0
                    priceInETH=0
                    usdPrice=0.0
                    paymentToken=None

                #seller may be in rare cases be null, so cannot chain easily
                walletSeller = openseaEvent['seller']
                if walletSeller is not None:
                    walletSeller = walletSeller['address']

                #Seller fee  = opensea cut + collection owner cut
                sellerFeeFactor = 0.0
                if openseaEvent['asset']['asset_contract']['seller_fee_basis_points']:
                    sellerFeeFactor = openseaEvent['asset']['asset_contract']['seller_fee_basis_points']/10000.0
                


                
                isTransferEvent = False
                if eventType=='successful':
                    transaction  = Transaction(openseaEvent['transaction']['transaction_hash'],transactionDate,eventType,priceInETH,openseaEvent['quantity'], paymentToken, usdPrice, sellerFeeFactor,walletSeller, openseaEvent['winner_account']['address'])
                elif eventType=='transfer':
                    isTransferEvent=True
                    if openseaEvent['transaction']:
                        transactionHash = openseaEvent['transaction']['transaction_hash']
                    else:#Some older transer events have transaction: null
                        transactionHash = openseaEvent['created_date']
                    transaction  = Transaction(transactionHash,transactionDate,eventType,priceInETH,openseaEvent['quantity'], paymentToken, usdPrice,sellerFeeFactor, openseaEvent['from_account']['address'], openseaEvent['to_account']['address'])
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

                    nft  = NFT(openseaEvent['asset']['asset_contract']['address'] ,openseaEvent['asset']['asset_contract']['name'],nftName,openseaEvent['asset']['description'],openseaEvent['asset']['token_id'],openseaEvent['asset']['permalink'],openseaEvent['asset']['image_url'],openseaEvent['asset']['image_preview_url'],)   
                else:
                    #print('Add transaction to existing NFT')
                    nft = self.nfts.get(asset_id)
                
                if transaction.isSeller(self.wallet):
                    nft.addSellTransaction(copy.copy(transaction),isTransferEvent,self)                  
                else:
                    nft.addBuyTransaction(copy.copy(transaction),isTransferEvent,self)   
                 
                
                self.nfts[asset_id]= nft
            except BaseException as ex:
                print("Failed parsing transaction")
                print(ex)
                print(json.dumps(openseaEvent,indent=4))
                raise
    
    def _getNftsTradeByContract(self,nftsTraded):
        #New table grouped by contract - A bit messy so consider splitting in to new function
        nftsTradedByContract = PrettyTable(["Contract name","Count","Profit USD","% profit","Sell USD","Buy USD"])
        nftsTradedByContract.set_style(DOUBLE_BORDER)
        nftsTradedByContract.float_format=".2"
        nftsTradedByContract.sortby="Profit USD"
        nftsTradedByContract.reversesort=True
        nftsTradedByContract.align = "l"
        #Use the data in nftsTraded as basis
        dataTradedNfts = nftsTraded.rows
        dataNFTSTradedByContract={}
        for row in dataTradedNfts:
            if row[7] in dataNFTSTradedByContract:
                currentRow = dataNFTSTradedByContract[row[7]]
                #Add to Sell USD and Buy USD
                currentRow[4] +=  row[5]
                currentRow[5] +=  row[6]
                currentRow[1] +=  row[9]
            else:
                contractName = row[8]
                if contractName =='Unidentified contract':
                    contractName=row[7]
                #Key contract hash, field sell USD and Buy USD used
                dataNFTSTradedByContract[row[7]]=[contractName,row[9],0.0,0.0,row[5],row[6]]

        sumProfits = 0.0
        for row in dataNFTSTradedByContract:
            dataNFTTraded = dataNFTSTradedByContract[row]
            #Profit USD = Sell USD - Buy USD
            dataNFTTraded[2]=dataNFTTraded[4]-dataNFTTraded[5]
            sumProfits+=dataNFTTraded[2]
            #% profit = ((profits)/totalBuyUSD)*100
            if dataNFTTraded[5] >0.0:
                dataNFTTraded[3] = ((dataNFTTraded[2])/dataNFTTraded[5])*100

            nftsTradedByContract.add_row(dataNFTSTradedByContract[row])

        return nftsTradedByContract

    def _getNFTSHoldingByContract(self,nftsHolding):
        #New table grouped by contract - A bit messy
        #nftsHoldings ["NFT name","Bought","Days held","Buy USD","Buy ETH","Break-even ETH","Contract hash", "Contract name"])
        nftsHoldingByContract = PrettyTable(["Contract name","Count holding", "Buy USD", "Buy ETH"])
        nftsHoldingByContract.set_style(DOUBLE_BORDER)
        nftsHoldingByContract.float_format=".2"
        nftsHoldingByContract.sortby="Buy USD"
        nftsHoldingByContract.reversesort=True
        nftsHoldingByContract.align = "l"
        #Use the data in nftsTraded as basis
        dataHoldingNfts = nftsHolding.rows
        dataNFTSHoldingByContract={}
        for row in dataHoldingNfts:
            if row[7] in dataNFTSHoldingByContract:
                currentRow = dataNFTSHoldingByContract[row[7]]
                #Add to Count holding, buy usd and buy eth
                currentRow[1] += 1
                currentRow[2] +=  row[3]
                currentRow[3] +=  row[4]
            else:
                contractName = row[8]
                if contractName =='Unidentified contract':
                    contractName=row[7]
                #Key contract hash, field sell USD and Buy USD used
                dataNFTSHoldingByContract[row[7]]=[contractName,1,row[3],row[4]]

        for row in dataNFTSHoldingByContract:
            nftsHoldingByContract.add_row(dataNFTSHoldingByContract[row])

        return nftsHoldingByContract

    def listNFTs(self):
        
        #NFTs with both buy and sold transaction

        #Table setup ref https://pypi.org/project/prettytable/
        #Note contract hash and name are not display, just used to generate a new table
        nftsTraded = PrettyTable(["NFT name","Bought","Days held","Profit USD","% profit","Sell USD","Buy USD","Contract hash", "Contract name","Count"])
        nftsTraded.set_style(DOUBLE_BORDER)
        nftsTraded.float_format=".2"
        nftsTraded.sortby="Sell USD"
        nftsTraded.reversesort=True
        nftsTraded.align = "l"

        nftsHolding = PrettyTable(["NFT name","Bought","Days held","Buy USD","Buy ETH","Break-even ETH","Sales fee","Contract hash", "Contract name"])
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

        hasNftsOnlySold=False
        for nftKey in self.nfts:
            nft = self.nfts[nftKey]
            nft.addToReport(nftsTraded,self.REPORT_PROFIT,self.historicEthPrice)
            nft.addToReport(nftsHolding,self.REPORT_HOLDING,self.historicEthPrice)
            nft.addToReport(nftsOnlySold,self.REPORT_ONLY_SOLD,self.historicEthPrice)

        #New table grouped by contract
        nftsTradedByContract=self._getNftsTradeByContract(nftsTraded)
        nftsHoldingByContract=self._getNFTSHoldingByContract(nftsHolding)
        

        #Remove the contract related columns from nftsTraded
        nftsTraded.del_column('Contract hash')
        nftsTraded.del_column('Contract name')
        nftsTraded.del_column('Count')

        print("Profit pr NFT")
        print(nftsTraded)
        print("Profit pr contract")
        print(nftsTradedByContract)
        #print("Total profits: {:.2f}".format(sumProfits))

        #print("Profits (USD) {:.2f}".format(profits))
        
        #Remove the contract related columns from nftsTraded
        nftsHolding.del_column('Contract hash')
        nftsHolding.del_column('Contract name')
        print("Currently holding:")
        print(nftsHolding)
        print(nftsHoldingByContract)
        
        if hasNftsOnlySold:
            print("Missing buy transaction:")
            #print("Total sell price where missing buy transaction {:.2f} USD".format(totalSoldMissingBuy))
            print(nftsOnlySold)

        sumProfits = 0.0
        dataNFTSTraded= nftsTraded.rows
        for row in dataNFTSTraded:
            # Cannot use Profit USD field as it is a string due to coloring
            #Using (sell USD-buy USD)
            sumProfits += (row[5]-row[6])
        print("Sum profits: {:.2f} USD".format(sumProfits))
        sumBuyForUnsold = 0.0
        dataNFTSHolding= nftsHolding.rows
        for row in dataNFTSHolding:
            sumBuyForUnsold += row[3]        
        print("Sum buy price for unsold nfts: {:.2f} USD".format(sumBuyForUnsold))

        print("\nDisclaimer: These numbers are based on transaction available in the OpenSea API.\nThe prices usually contains minting and seller fees.\nPrices do not include transaction costs.\nThe numbers are not thoroughly vetted, so don't use as a basis for Tax reporting purposes.\nMade by elsewhat.eth - @dparnas")

class NFT:
    def __init__(self, contractAddress,contractName,nftName,nftDescription,contractTokenId,openseaLink,imageUrl,imagePreviewUrl):
        self.contractAddress = contractAddress
        self.contractName = contractName
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
                #Reduce sellTransaction on the seller fee (usually 2.5% opensea and x% collection owner)
                profits+= (sellTransaction.usdPrice * (1.0-sellTransaction.sellerFeeFactor))- buyTransaction.usdPrice

        return profits
 
    def addBuyTransaction(self, transaction, isTransferEvent, walletNFTHistory):
        existingBuyTransaction,existingSellTransaction = self.__walletTransactions[0]

        if not isTransferEvent:
            for index, walletTransaction in enumerate(self.__walletTransactions):
                #print("Creating new buy transaction for {}".format(self.nftName))
                currentBuyTransaction,currentSellTransaction = walletTransaction
                if currentBuyTransaction == None:
                    #if index > 0:
                        #print("Adding additional buy for {}".format(self.nftName))
                    self.__walletTransactions[index]=(transaction,currentSellTransaction)
                    return
        elif isTransferEvent==True and not existingBuyTransaction:
            transactionLookupURL = "https://api.blockcypher.com/v1/eth/main/txs/{}".format(transaction.transactionHash)
            print("REQUEST: {}".format(transactionLookupURL))
            try:
                response = requests.get(transactionLookupURL)
                transactionLookup = response.json()
                ethPrice = transactionLookup['total']*1.0e-18
                if ethPrice > 0.0:
                    print("Adding {:.2f} of mint cost to transaction {}".format(ethPrice,transaction.transactionHash))
                    transaction.price = ethPrice
                    transaction.recalculateUSDPrice(walletNFTHistory.historicEthPrice)
            except requests.exceptions.HTTPError as error:
                print(transactionLookup)
                print(error)

            #self.__buyTransaction = transaction   
            self.__walletTransactions[0] = (transaction,existingSellTransaction)
    
    def addSellTransaction(self, transaction, isTransferEvent,walletNFTHistory):
        existingBuyTransaction,existingSellTransaction = self.__walletTransactions[0]

        #Check if we've owned this NFT more than once
        # if last entry in __walletTransactions already has a sellTransaction, add a new entry
        if not isTransferEvent:
            _,lastSellTransaction = self.__walletTransactions[len(self.__walletTransactions)-1]
            if lastSellTransaction!= None:
                #print("Creating new sell transaction for {}".format(self.nftName))
                self.__walletTransactions.append((None,transaction))
                return       

        if isTransferEvent==False:
            #self.__sellTransaction = transaction
            self.__walletTransactions[0] = (existingBuyTransaction,transaction)
        elif isTransferEvent==True and not existingSellTransaction:
            #self.__sellTransaction = transaction
            self.__walletTransactions[0] = (existingBuyTransaction,transaction)


    def addToReport(self,prettyTableForReport, reportType,historicEthPrice):
        buyTransaction,sellTransaction = self.__walletTransactions[0]

        if reportType == WalletNFTHistory.REPORT_PROFIT:
            if buyTransaction and sellTransaction:    
                prettyTableForReport.add_row(self.getTableOutput(historicEthPrice))
        elif reportType == WalletNFTHistory.REPORT_HOLDING:
            if buyTransaction and not sellTransaction:
                prettyTableForReport.add_row(self.getTableOutput(historicEthPrice))
        elif reportType == WalletNFTHistory.REPORT_ONLY_SOLD:      
            if sellTransaction and not buyTransaction:
               prettyTableForReport.add_row(self.getTableOutput(historicEthPrice)) 
        else:
            print("Unsupported report type {}".format(reportType))      

    def getTableOutput(self,historicEthPrice):
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
            dateFirstBought=datetime.now()
            #Sum together for multiple sales
            for walletTransaction in self.__walletTransactions: 
                buyTransaction,sellTransaction = walletTransaction
                if buyTransaction and sellTransaction:
                    countSold+=1
                    if buyTransaction.transactionDate< dateFirstBought:
                        dateFirstBought=buyTransaction.transactionDate
                    daysHeld =(sellTransaction.transactionDate- buyTransaction.transactionDate).days
                    if buyTransaction and sellTransaction and sellTransaction.transactionType != 'transfer':
                        totalBuyUSD += buyTransaction.usdPrice
                        #Reduce usd price based on the seller fee (usually 2.5% opensea and x% collection owner)
                        totalSellUSD += sellTransaction.usdPrice * (1.0-sellTransaction.sellerFeeFactor)
                    

            daysHeld= int(daysHeld/countSold)
            profitPercentage=0.0
            #Avoid divide by zero in rare cases
            if totalBuyUSD >0.0:
                profitPercentage = ((profits)/totalBuyUSD)*100

            nftName = self.nftName
            if countSold >1:
                nftName += ' x {}'.format(countSold)

            return [nftName,"{}".format(dateFirstBought.strftime('%Y-%m-%d')),daysHeld,profitColor +'{:.2f}'.format(profits)+Back.RESET,  profitPercentage,totalSellUSD,totalBuyUSD,self.contractAddress,self.contractName,countSold]
        elif buyTransaction:
            #Takes the last historic price (get the keys, make it into a list and take the last item)
            ethPriceNow = historicEthPrice[list(historicEthPrice.keys())[-1]]
            totalBuyUSD=0.0
            totalBuyETH=0.0
            countHolding = 0
            daysHeld=0
            dateFirstBought=datetime.now()
            #Sum together for multiple sales
            for walletTransaction in self.__walletTransactions: 
                buyTransaction,_ = walletTransaction
                if buyTransaction.transactionDate< dateFirstBought:
                    dateFirstBought=buyTransaction.transactionDate              
                if buyTransaction:
                    totalBuyUSD += buyTransaction.usdPrice
                    totalBuyETH += buyTransaction.price
                    countHolding+=1
                    daysHeld +=(datetime.now()- buyTransaction.transactionDate).days

            daysHeld= int(daysHeld/countHolding)
            breakEven = totalBuyUSD/ethPriceNow
            avgBuyEth = totalBuyETH/countHolding

            nftName = self.nftName
            if countHolding >1:
                nftName += ' x {}'.format(countHolding)

            salesFee = buyTransaction.sellerFeeFactor*100.0

            return [nftName,"{}".format(dateFirstBought.strftime('%Y-%m-%d')),daysHeld,totalBuyUSD, avgBuyEth, breakEven,salesFee,self.contractAddress,self.contractName]
        elif sellTransaction:
            #Does not handle multiple of the same nft held , but that's ok
            return [self.nftName,"{}".format(sellTransaction.transactionDate.strftime('%Y-%m-%d')), '', '',sellTransaction.usdPrice,'']   

class Transaction:
    def __init__(self, transactionHash,transactionDate,transactionType, price,quantity,paymentToken, usdPrice, sellerFeeFactor, walletSeller, walletBuyer):
        self.transactionHash=transactionHash
        self.transactionDate=transactionDate
        self.transactionType=transactionType
        self.price = price
        self.quantity = quantity
        self.paymentToken=paymentToken
        self.usdPrice=usdPrice
        self.sellerFeeFactor = sellerFeeFactor
        self.walletSeller=walletSeller
        self.walletBuyer= walletBuyer

    def isSeller(self,wallet):
        #Important to make case-insensitive compare
        if wallet and self.walletSeller and self.walletSeller.casefold()==wallet.casefold():
            return True
        else: 
            return False

    def isBuyer(self,wallet):
        if self.walletBuyer==wallet:
            return True
        else: 
            return False

    def recalculateUSDPrice(self,historicEthPrice):
        transactionYYYYMMDD = self.transactionDate.strftime('%Y-%m-%d')
        if transactionYYYYMMDD in historicEthPrice:
            ethpriceAtTransaction = historicEthPrice[transactionYYYYMMDD]
        else:
            # Dict keys are ordered ref https://stackoverflow.com/a/16125237/250787 so safe to do this
            keyLastDate = list(historicEthPrice.keys())[-1]
            ethpriceAtTransaction = historicEthPrice[keyLastDate]
            print("WARNING: ethprice.csv does not contain a value for {}. Using value {:.2f} for {} instead.".format(transactionYYYYMMDD,ethpriceAtTransaction,keyLastDate) )
        
        self.usdPrice = self.price*ethpriceAtTransaction

    

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
    openseaAPIKey = sys.argv[2]

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

    headers = { 'X-API-KEY': openseaAPIKey,
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
        print(error.response.text())
    


if __name__ == '__main__':
   main()