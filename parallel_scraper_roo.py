# This is a test script for the rental listing scraper
from datetime import datetime as dt
from datetime import timedelta
import time
import sys
import os
import multiprocessing
import shutil
import subprocess
import glob
sys.path.insert(0, './shared_room_scraper')
import roodata_to_database

# add subfolder to system path

domains = []
with open('./domains_roo.txt', 'rb') as f:
    for line in f.readlines():
        domains.append((line.strip()))

domains = ['http://losangeles.craigslist.org/search/roo']

lookback = 2  # hours

earliest_ts = dt.now() - timedelta(hours=lookback)
latest_ts = dt.now() + timedelta(hours=1)
ts = dt.now().strftime('%Y%m%d-%H%M%S')

jobs = []

st_time = time.time()
for domain in domains:
    s = roodata_to_database.RentalListingScraper(    #is ours RentalListingScraper?
        domains=[domain],
        earliest_ts=earliest_ts,
        latest_ts=latest_ts,
        fname_ts=ts)
    print ('Starting process for ' + domain)
    p = multiprocessing.Process(target=s.run)
    jobs.append(p)
    p.start()

for i, job in enumerate(jobs):
    job.join()
    end_time = time.time()
    elapsed_time = end_time - st_time
    time_per_domain = elapsed_time / (i + 1.0)
    num_domains = len(jobs)
    domains_left = num_domains - (i + 1.0)
    time_left = domains_left * time_per_domain
    print("Took {0} seconds for {1} regions.".format(elapsed_time, i + 1))
    print("About {0} seconds left.".format(time_left))

# archive the data and delete the raw files
# print("Archiving data.")

# shutil.make_archive('/home/mgardner/scraper2/archives/rental_listings-' + ts,
#                     'zip', '/home/mgardner/scraper2/data')
# [os.remove(x) for x in glob.glob("/home/mgardner/scraper2/data/*" +
#                                  ts + ".csv")]

# # run the sync script to send the archive to box, delete local copy of archive
# p = subprocess.Popen(['. /home/mgardner/scraper2/sync_data.sh'], shell=True,
#                      stdin=subprocess.PIPE, stdout=subprocess.PIPE)
# print("Done.")
