
# coding: utf-8

# # Shared Room Scraper
# This notebook implements a variation on the scraper2.py that scrapes shared listings rather than apartments/hohusing rental listings. This is a project of the Urban Analytics Lab at UC Berkeley. In order to run this file, the user needs to define a private 'settings.json' file in the directory of the code. This file contains the credentials for the database host, name, and password.

# In[ ]:

#Import required packages
from datetime import datetime as dt
from datetime import timedelta
import logging
import importlib
import urllib
import unicodecsv as csv
from lxml import html
import requests
import pandas as pd
import numpy as np
import json
import sys
from requests.auth import HTTPProxyAuth
import time
import psycopg2
pd.set_option('display.float_format', lambda x: '%.3f' % x) #describe() vars are not in scientific notation
pd.set_option('max_columns', 30)


# In[ ]:

#For Database
# Read in credentials from private settings file
# with open('settings.json') as settings_file:    
#     settings = json.load(settings_file)


# In[ ]:

#charity, proxy, s, sessions variables are associated with the charity engine
#Try to run this with San Francisco
DOMAINS = []

#Craigslist doesn't use time zones in its timestamps, so these cutoffs will be
#interpreted relative to the local time at the listing location. For example, dt.now()
#run from a machine in San Francisco will match listings from 3 hours ago in Boston.
LATEST_TS = dt.now() - timedelta(hours=1)  #lagged lookback to account for the delay we're getting in our results
EARLIEST_TS = LATEST_TS - timedelta(hours=2)


OUT_DIR = "./data" #Istanbul directory
#OUT_DIR ="C:\\Users\\james\\Documents\\Berkeley_Docs\\Spring_17_Courses\\CP290 Data Lab\\scraper_output\\" #James's directory
#OUT_DIR ="C:\\Users\\varun\\Documents\\Berkeley\\2017 Spring\\Workshop\\Datasets\\data_output\\" #Varun's directory
#OUT_DIR ='/Users/anniedbr/Desktop/CSV/'  #Annie's directory
#OUT_DIR ='../../Scraped Listings/'  #Brian's directory

FNAME_BASE = 'data'  # filename prefix for saved data
FNAME_TS = True  # append timestamp to filename

S3_UPLOAD = False
S3_BUCKET = 'scraper2'

class RentalListingScraper(object):

    def __init__(
            self, 
            domains = DOMAINS,
            earliest_ts = EARLIEST_TS,
            latest_ts = LATEST_TS, 
            out_dir = OUT_DIR,
            fname_base = FNAME_BASE,
            fname_ts = FNAME_TS,
            s3_upload = S3_UPLOAD,
            s3_bucket = S3_BUCKET):
        
        self.domains = domains
        self.earliest_ts = earliest_ts
        self.latest_ts = latest_ts
        self.out_dir = out_dir
        self.fname_base = fname_base
        self.fname_ts = fname_ts
        self.s3_upload = s3_upload
        self.s3_bucket = s3_bucket
        self.ts = dt.now().strftime('%Y%m%d-%H%M%S')  # Use timestamp as file id
        #self.ts = fname_ts

        log_fname = self.out_dir + self.fname_base                 + (self.ts if self.fname_ts else '') + '.log'
        
        importlib.reload(logging)
        
        logging.basicConfig(filename=log_fname, level=logging.INFO)
       

        
    def _get_str(self, list):
        '''
        The xpath() function returns a list of items that may be empty. Most of the time,
        we want the first of any strings that match the xml query. This helper function
        returns that string, or null if the list is empty.
        '''
        
        if len(list) > 0:
            return list[0]

        return ''
    
        
    def _get_int_prefix(self, str, label):
        '''
        Bedrooms and square footage have the format "xx 1br xx 450ft xx". This helper 
        function extracts relevant integers from strings of this format.
        '''     
        
        for s in str.split(' '):
            if label in s:
                return s.strip(label)
                
        return 0


    def _toFloat(self, string_value):
        string_value = string_value.strip()
        return np.float(string_value) if string_value else np.nan
 
    


    def _parseListing(self, item):
        '''
        Note that xpath() returns a list with elements of varying types depending on the
        query results: xml objects, strings, etc.
        '''
        pid = item.xpath('@data-pid')[0]  # post id, always present
        info = item.xpath('p[@class="result-info"]')[0]
        dt = info.xpath('time/@datetime')[0]
        url = info.xpath('a/@href')[0]
        if type(info.xpath('a/text()')) == str:
            title = info.xpath('a/text()')
        else:
            title = info.xpath('a/text()')[0]
        price = self._get_str(info.xpath('span[@class="result-meta"]/span[@class="result-price"]/text()')).strip('$')
        neighb_raw = info.xpath('span[@class="result-meta"]/span[@class="result-hood"]/text()')
        if len(neighb_raw) == 0:
            neighb = ''
        else:
            neighb = neighb_raw[0].strip(" ").strip("(").strip(")")
        housing_raw = info.xpath('span[@class="result-meta"]/span[@class="housing"]/text()')
        if len(housing_raw) == 0:
            #beds = 0
            sqft = 0
        else:
            bedsqft = housing_raw[0]
            sqft = self._get_int_prefix(bedsqft, "ft")  # appears as "000ft" or missing

        return [pid, dt, url, title, price, neighb, sqft]

    

    def PageBodyText(self, session, url, proxy=True):
        #this grabs the entire XML structured text from each post, then cleans it a bit.  
        
        s = session
        #page = requests.get(url)        
        page = s.get(url, timeout=30, verify=False)
        tree = html.fromstring(page.content)
        path = tree.xpath('//section[@id="postingbody"]')[0]
               
        body_list = path.xpath('text()')
        
        body_text = ''.join(body_list).strip().encode('utf-8')
        
        return [body_text]
     
    def _scrapeLatLng(self, session, url, proxy=True):
    
        s = session
        # if proxy:
        #     requests.packages.urllib3.disable_warnings()
        #     authenticator = '87783015bbe2d2f900e2f8be352c414a'
        #     proxy_str = 'http://' + authenticator + '@' +'workdistribute.charityengine.com:20000'
        #     s.proxies = {'http': proxy_str, 'https': proxy_str}
        #     s.auth = HTTPProxyAuth(authenticator,'') 

        page = s.get(url, timeout=30, verify=False)
        #page = requests.get(url)
        tree = html.fromstring(page.content)
       
        map = tree.xpath('//div[@id="map"]')

        # Sometimes there's no location info, and no map on the page        
        if len(map) == 0:
            return [99, 99, 99]

        map = map[0]
        lat = map.xpath('@data-latitude')[0]
        lng = map.xpath('@data-longitude')[0]
        
        
        accuracy = map.xpath('@data-accuracy')[0]

        return [lat, lng, accuracy]
   
    def PageAttributes(self, session, url, proxy=True):   
        '''
        Here we're parsing through the section in each listing that provides amenity information in one long string of text within a span tag 
        '''
        
        s = session
         
        page = s.get(url, timeout=30, verify=False)  
        tree = html.fromstring(page.content)
        
        attrs  = tree.xpath('/html/body/section/section/section/div[1]/p[2]/span') 

        furnished = any(['furnished' in attr.text for attr in attrs]) # A "False" doesn't necessarily mean the unit isn't furnished
    
        laundry_possible1 = any(['laundry' in attr.text for attr in attrs])
        laundry_possible2 = any(['w/d' in attr.text for attr in attrs])
        
        if (laundry_possible1 == True or laundry_possible2 == True):
            laundry_known = 'TRUE'
        else:
            laundry_known = 'FALSE'
            
        no_laundryonsite1 = any(['no laundry' in attr.text for attr in attrs])
        no_laundryonsite2 = any(['hookups' in attr.text for attr in attrs]) #haven't come accross one of these yet so not positive it's working
        
        if (no_laundryonsite1 == True or no_laundryonsite2 == True):
            no_laundryonsite = 'TRUE'
        else:
            no_laundryonsite = 'FALSE' 
        
        laundry_inunit = any(['w/d in unit' in attr.text for attr in attrs])   
        
        if (laundry_known == 'TRUE' and no_laundryonsite == 'FALSE' and laundry_inunit == False): 
            laundry_onpremises = 'TRUE'    
        else:
            laundry_onpremises = 'FALSE'      

        room_known = any(['room' in attr.text for attr in attrs])
        
        private_room1 = any(['private room' in attr.text for attr in attrs])
        
        if(room_known == True and private_room1 == True):
            private_room = 'TRUE'
        else:
            private_room = 'FALSE'
                        
        bath_known = any(['bath' in attr.text for attr in attrs])
        bath_possible = any(['private bath' in attr.text for attr in attrs])
        no_bath = any(['no private bath' in attr.text for attr in attrs])  
        if(bath_possible == True and no_bath== False):           
            private_bath = 'TRUE' 
        else:
            private_bath = 'FALSE'
        
        parking_knowna = any(['carport' in attr.text for attr in attrs])
        parking_knownb = any(['attached garage' in attr.text for attr in attrs])
        parking_knownc = any(['off-street parking' in attr.text for attr in attrs])
        parking_knownd = any(['detached garage' in attr.text for attr in attrs])
        parking_knowne = any(['street parking' in attr.text for attr in attrs])
        parking_knownf = any(['valet parking' in attr.text for attr in attrs])
        parking_knowng = any(['no parking' in attr.text for attr in attrs])
        if(parking_knowna == True or parking_knownb== True or parking_knownc== True or parking_knownd== True or parking_knowne== True or parking_knownf== True or parking_knowng== True):           
            parking_known = 'TRUE' 
        else:
            parking_known = 'FALSE'
        
        parking_poss1 = any(['carport' in attr.text for attr in attrs])
        parking_poss2 = any(['attached garage' in attr.text for attr in attrs])
        parking_poss3 = any(['off-street parking' in attr.text for attr in attrs])
        parking_poss4 = any(['detached garage' in attr.text for attr in attrs])
        parking_poss5 = any(['valet parking' in attr.text for attr in attrs])
        if(parking_poss1 == True or parking_poss2== True or parking_poss3== True or parking_poss4== True or parking_poss5== True):           
            parking_poss = 'TRUE' 
        else:
            parking_poss = 'FALSE'                     
                             
        no_onsiteparking1 = any(['no parking' in attr.text for attr in attrs])
        no_onsiteparking2 = any(['street parking' in attr.text for attr in attrs])
        if(no_onsiteparking1 == True or no_onsiteparking2== True):           
            no_onsiteparking = 'TRUE' 
        else:
            no_onsiteparking = 'FALSE'
         
        if (parking_poss == 'TRUE' and no_onsiteparking == 'FALSE'):
             parking_onsite = 'TRUE'
        else:
             parking_onsite = 'FALSE'

        return [furnished, laundry_known, laundry_onpremises, laundry_inunit, room_known, private_room, bath_known, private_bath, parking_known, parking_onsite]    
     
    def _get_fips(self, row):
        url = 'http://data.fcc.gov/api/block/find?format=json&latitude={}&longitude={}'
        request = url.format(row['latitude'], row['longitude'])
        # TO DO: exception handling
        response = requests.get(request)
        data = response.json()
        return pd.Series({'fips_block':data['Block']['FIPS'], 'state':data['State']['code'], 'county':data['County']['name']})

    def _clean_listings(self, filename):

            converters = {'neighb':str, 
                  'title':str, 
                  'price':self._toFloat, 
                  'pid':str, 
                  'dt':str, 
                  'url':str, 
                  'sqft':self._toFloat, 
                  'lng':self._toFloat, 
                  'lat':self._toFloat}

            all_listings = pd.read_csv(filename, converters=converters)

            if len(all_listings) == 0:
                return [], 0, 0, 0
                print('{0} total listings'.format(len(all_listings)))

            all_listings = all_listings.rename(columns={'price':'rent', 'dt':'date', 'neighb':'neighborhood',
                                                        'lng':'longitude', 'lat':'latitude'})
            all_listings['rent_sqft'] = all_listings['rent'] / all_listings['sqft']
            all_listings['date'] = pd.to_datetime(all_listings['date'], format='%Y-%m-%d')
            all_listings['day_of_week'] = all_listings['date'].apply(lambda x: x.weekday())
            all_listings['region'] = all_listings['url'].str.extract('http://(.*).craigslist.org', expand=False)
            unique_listings = pd.DataFrame(all_listings.drop_duplicates(subset='pid', inplace=False))
            thorough_listings = pd.DataFrame(unique_listings)
            if len(thorough_listings) == 0:
                return [], 0, 0, 0

            cols = ['pid', 'date', 'day_of_week', 'url', 'title', 'rent', 'rent_sqft', 'neighborhood', 'region', 'sqft', 'latitude', 'longitude',
                    'accuracy', 'body_text', 'furnished', 'laundry_known', 'laundry_onpremises', 
                    'laundry_inunit','room_known', 'private_room', 'bath_known', 'private_bath', 'parking_known', 
                    'onsite_parking']
            data_output = thorough_listings[cols]
            #we are not including fips codes yet: still need to resolve missing lat-long issue (won't work with fips code function)
            #fips = data_output.apply(self._get_fips, axis=1)             
            #geocoded = pd.concat([data_output, fips], axis=1)
            return data_output, len(all_listings), len(thorough_listings), len(data_output)
    
    def _write_db(self, dataframe, domain):
        '''
        This function takes in the cleaned dataframe from the cleaning function
        and exports it to a PostgreSQL database table.
        '''
        dbname = settings['dbname']
        user = settings['user']
        host = settings['host']
        passwd = settings['password']
        conn_str = "dbname={0} user={1} host={2} password={3}".format(dbname,user,host,passwd)
        conn = psycopg2.connect(conn_str)
        cur = conn.cursor()
        num_listings = len(dataframe)
        # print("Inserting {0} listings from {1} into database.".format(num_listings, domain))
        prob_PIDs = []
        dupes = []
        writes = []
        for i,row in dataframe.iterrows():
            try:
                cur.execute('''INSERT INTO shared_listings
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, %s, %s, %s)''',
                    (row['pid'],pd.to_datetime(row['date']), row['day_of_week'], row['url'],row['title'],
                    row['rent'], row['rent_sqft'], row['neighborhood'], row['region'], row['sqft'],row['latitude'],
                    row['longitude'],row['accuracy'],row['body_text'],
                    row['furnished'],row['laundry_known'],row['laundry_onpremises'],
                    row['laundry_inunit'],row['room_known'],row['private_room'],
                    row['bath_known'],row['private_bath'],row['parking_known'],row['onsite_parking']))
                conn.commit()
                writes.append(row['pid'])

            except Exception as e:
                if 'duplicate key value violates unique' in str(e):
                    dupes.append(row['pid'])
                else:
                    prob_PIDs.append(str(row['pid']))
                conn.rollback()

        cur.close()
        conn.close()
        return prob_PIDs, dupes, writes
    
    def run(self, charity_proxy=True):
        
            colnames = ['pid','dt','url','title','price','neighb','sqft',
                        'lat','lng','accuracy','body_text', 'furnished', 'laundry_known', 'laundry_onpremises', 'laundry_inunit', 'room_known', 'private_room', 'bath_known', 'private_bath', 'parking_known', 'onsite_parking']     
            st_time = time.time()
        
            #st+time = time.time()
            #LOOP ALL REGIONS ONE DOMAIN AT A TIME
            for domain in self.domains:
                
                total_listings = 0
                listing_num = 0
                ts_skipped = 0
                
                regionName = domain.split('//')[1].split('.craigslist')[0]
                fname = self.out_dir + self.fname_base + '-' + regionName + (self.ts if self.fname_ts else '') + '.csv'
                regionIsComplete = False
                search_url = domain
                print("beginning new region")
                logging.info('BEGINNING NEW REGION')
                        
                with open(fname, 'wb') as f:
                    writer = csv.writer(f)
                    writer.writerow(colnames)
                    
                    while not regionIsComplete:
                        
                        logging.info(search_url)
                        s = requests.Session()
                        
                        if charity_proxy:
                            requests.packages.urllib3.disable_warnings()
                            authenticator = '87783015bbe2d2f900e2f8be352c414a'
                            proxy_str = 'http://' + authenticator +':foo'+ '@' +'workdistribute.charityengine.com:20000'
                            s.proxies = {'http': proxy_str, 'https': proxy_str}
                            s.auth = HTTPProxyAuth(authenticator,'')

                        try:
                            page = s.get(search_url, timeout=30, verify=False)
                        except requests.exceptions.Timeout:
                            s = requests.Session()
                            if charity_proxy:
                                s.proxies = {'http': proxy_str, 'https': proxy_str}
                                s.auth = HTTPProxyAuth(authenticator,'')
                            try:
                                page = s.get(search_url, timeout=30, verify=False)    
                            except:
                                regionIsComplete = True
                                logging.info('FAILED TO CONNECT.')

                        try:
                            tree = html.fromstring(page.content)
                        except:
                            regionIsComplete = True
                            logging.info('FAILED TO PARSE HTML.')
                        
                        
                        #page = requests.get(search_url)
                        print(page.status_code)
                        tree = html.fromstring(page.content)
                        #return tree
                            
                        listings = tree.xpath('//li[@class="result-row"]')
                        print("got {0} listings".format(len(listings)))
                        
                        if len(listings) == 0 and total_listings == 0:
                            logging.info('NO LISTINGS RETRIEVED FOR {0}'.format(str.upper(regionName)))

                        total_listings += len(listings)
                        
                        for item in listings:
                            listing_num += 1
                            try:
                                row = self._parseListing(item)
                                item_ts = dt.strptime(row[1], '%Y-%m-%d %H:%M')
                
                                if (item_ts > self.latest_ts):
                                # Skip this item but continue parsing search results
                                    ts_skipped += 1
                                    continue

                                if (item_ts < self.earliest_ts):
                                # Break out of loop and move on to the next region
                                    if listing_num == 1:
                                        logging.info('NO LISTINGS BEFORE TIMESTAMP CUTOFF AT {0}'.format(str.upper(regionName)))    
                                    else:
                                        logging.info('REACHED TIMESTAMP CUTOFF')
                                    ts_skipped += 1
                                    regionIsComplete = True
                                    logging.info('REACHED TIMESTAMP CUTOFF')
                                    break 
                    
                                item_url = domain.split('/search/roo')[0] + row[2]
                                row[2] = item_url
                                #item_url = domain.split('/search')[0] + tree.xpath('a/@href')[0]
                                logging.info(item_url)
                                row += self._scrapeLatLng(s, item_url)
                                row += self.PageBodyText(s, item_url)
                                row += self.PageAttributes(s, item_url)
                                writer.writerow(row)
                            
                            except Exception as e:
                            # Skip listing if there are problems parsing it
                                logging.warning("{0}: {1}. Probably no beds/sqft info".format(type(e).__name__, e))
                                continue
                                   
                        next = tree.xpath('//a[@title="next page"]/@href')
                        if len(next) > 0:
                            search_url = domain.split('/search')[0] + next[0]
                        else:
                            regionIsComplete = True
                            logging.info('RECEIVED ERROR PAGE')       
                        s.close()
                #print tr_skipped
# ONCE CLEANING AND DATABASE FUNCTIONS ARE TESTED AND COMPLETE, THE FOLLOWING SECTION CAN BE BROUGHT BACK                

#                 if ts_skipped == total_listings:
#                     logging.info(('{0} TIMESTAMPS NOT MATCHING' + '- CL: {1} vs. ual: {2}.' + ' NO DATA SAVED.').format(regionName,str(item_ts),str(self.latest_ts)))
#                     continue
#                 #passing for now. When finished writing cleaning function, we will expand on this section
#                 cleaned, count_listings, count_thorough, count_geocoded = self._clean_listings(fname)
#                 num_cleaned = len(cleaned)
#                 #cleaned.to_csv(OUT_DIR+"/cleaned.csv") this step doesn't seem to be working, but shouldn't be necessary.
#                 if num_cleaned >0:
#                     probs, dupes, writes = self._write_db(cleaned, domain)
#                     num_probs = len(probs)
#                     num_dupes = len(dupes)
#                     num_writes = len(writes)
#                     pct_written = (num_writes) / num_cleaned * 100
#                     pct_fail = round(num_probs / num_cleaned * 100,3)
#                     if num_dupes == num_cleaned:
#                         logging.info('100% OF {0} PIDS ARE DUPES. NOTHING WRITTEN'.format(str.upper(regionName)))
                    
#                     else:
#                         logging.info('FAILED TO WRITE {0}% OF {1} PIDS:'.format(pct_fail,str.upper(regionName)) + ', '.join(probs))
#                 else: 
#                     #passing for now. When finished writing cleaning function, we will expand on this section
#                     pass
                
            return