import datetime
import requests
import sys
import json

def main():
    outputFilename = sys.argv[1]
    with open(outputFilename, 'w') as outputFile:

        requestDate = datetime.datetime(2020,1,1)
        endDate = datetime.datetime(2020,12,31)

        headers = { 'Authorization':'Authorization: Bearer abd90df5f27a7b170cd775abf89d632b350b7c1c9d53e08b340cd9832ce52c2c'}    
        while requestDate <= endDate:
            query = {'date': requestDate.strftime('%Y-%m-%d') }

            response = requests.get('https://api.coinbase.com/v2/prices/ETH-USD/spot', params=query,headers=headers)
            if response.status_code==200:
                data = response.json()
                ethUSDPrice = float(data['data']['amount'])
                outputFile.write("{},{:.2f}\n".format(requestDate.strftime('%Y-%m-%d'),ethUSDPrice))
            else:
                #Could be 429 rate limited or 400 (if date is in the future)
                print("Response status code {} . Exiting".format(response.status_code))
                print(response.json())
                break
                
            requestDate += datetime.timedelta(days=1)

if __name__ == '__main__':
   main()