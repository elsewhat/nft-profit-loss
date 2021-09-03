import requests
import sys
import json

class WalletNFTHistory: 
    wallet = None
    nfts = []

    def __init__(self, wallet):
        self.wallet = wallet
    
    def processOpenseaAPIResponse(self, openseaEvents):
        print(openseaEvents)


class NFT:
    buyTransaction = None
    sellTransaction = None

    def __init__(self, contractAddress,contractName,contractDescription,contractTokenId,openseaLink,imageUrl,imagePreviewUrl):
        self.contractAddress = contractAddress
        self.contractName = contractName
        self.contractDescription = contractDescription
        self.contractTokenId = contractTokenId
        self.openseaLink = openseaLink
        self.imageUrl = imageUrl
        self.imagePreviewUrl = imagePreviewUrl


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


def main():
    wallet = sys.argv[0]
    #openseaAPIKey = sys.argv[1]
    walletNFTHistory = WalletNFTHistory(wallet)


    query = {   'account_address':wallet, 
                'event_type':'successful', 
                'event_type':'transfer',
                'only_opensea':False,
                #'occured_before':'31.12.2021',  #Needs to be unix epoch style
                #'occured_after':'01.01.2021',
                'offset': 0,
                'limit':1}

    headers = { #'X-API-KEY': openseaAPIKey,
                'Accepts':'application/json'}                
    try:
        response = requests.get('https://api.opensea.io/api/v1/events', params=query,headers=headers)
        response.raise_for_status()

        openseaEvents = response.json()
        walletNFTHistory.processOpenseaAPIResponse(openseaEvents)
        # Additional code will only run if the request is successful
    except requests.exceptions.HTTPError as error:
        print(error)
    #


if __name__ == '__main__':
   main()