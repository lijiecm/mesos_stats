#!/usr/bin/env python -u
import os
import sys
import time
import traceback
from datetime import datetime

from mesos_stats.util import log, Timer
from mesos_stats.mesos import (
    cluster_metrics,
    Mesos,
    MesosStatsException,
    slave_metrics,
    slave_task_metrics,
)
from mesos_stats.carbon import Carbon
from mesos_stats.singularity import Singularity, singularity_metrics

DRY_RUN = False # Enable test mode. No stats sent to Graphite

def init_env():
    master_host = os.environ['MESOS_MASTER']
    carbon_host = os.environ['CARBON_HOST']
    graphite_prefix = os.environ['GRAPHITE_PREFIX']
    singularity_host = os.environ.get('SINGULARITY_HOST', None)
    dry_run = os.environ.get('DRY_RUN', DRY_RUN)
    master_pid = "%s:5050" % master_host

    if not all([master_host, carbon_host, graphite_prefix]):
        print('One or more configuration env not set')
        print_config()
        sys.exit(0)

    print("Got configuration...")
    print("MESOS MASTER:     %s" % master_pid)
    print("CARBON:           %s" % carbon_host)
    print("GRAPHITE PREFIX:  %s" % graphite_prefix)
    print("SINGULARITY HOST: %s" % singularity_host)
    print("DRY RUN (TEST MODE): %s" % dry_run)
    print("==========================================")

    mesos = Mesos(master_pid)
    carbon = Carbon(carbon_host, graphite_prefix, dry_run=dry_run)

    if singularity_host:
        singularity = Singularity(singularity_host)

    return (mesos, carbon, singularity)

def wait_until_beginning_of_clock_minute():
    iter_start = time.time()
    now = datetime.fromtimestamp(iter_start)
    sleep_time = 60.0 - ((now.microsecond/1000000.0) + now.second)
    log("Sleeping for %ss" % sleep_time)
    time.sleep(sleep_time)

def main_loop(mesos, carbon, singularity):
    should_exit = False
    # self-monitoring
    last_cycle_time = 0
    last_collection_time = 0
    last_send_time = 0
    assert all([mesos, carbon]) # Mesos and Carbon is mandatory
    while True:
        try:
            wait_until_beginning_of_clock_minute()
            with Timer("Entire collect and send cycle"):
                timestamp = time.time()
                now = datetime.fromtimestamp(timestamp)
                log("Timestamp: %s (%s)" % (now, timestamp))
                cycle_timeout = timestamp + 59.0
                metrics = []
                if mesos:
                    with Timer("Mesos metrics collection"):
                        mesos.reset()
                        metrics += slave_metrics(mesos)
                        metrics += slave_task_metrics(mesos)
                        metrics += cluster_metrics(mesos)
                if singularity:
                    with Timer("Singularity metrics collection"):
                        singularity.reset()
                        metrics += singularity_metrics(singularity)
                if not metrics:
                    log("No stats this time; sleeping")
                else:
                    send_timeout = cycle_timeout - time.time()
                    log("Sending stats (timeout %ss)" % send_timeout)
                    with Timer("Sending stats to graphite"):
                        carbon.send_metrics(metrics, send_timeout, timestamp)
        except MesosStatsException as e:
            log("%s" % e)
        except (KeyboardInterrupt, SystemExit):
            print("Bye!")
            should_exit = True
            sys.exit(0)
            break
        except Exception as e:
            traceback.print_exc()
            log("Unhandled exception: %s" % e)
        except object as o:
            traceback.print_exc()
            log("Unhandled exception object: %s" % o)
        except:
            traceback.print_exc()
            log("Unhandled unknown exception.")
        else:
            log("Metrics sent successfully.")
        finally:
            if should_exit:
                return

if __name__ == '__main__':
    (mesos, carbon, singularity) = init_env()
    start_time = time.time()
    print("Start time: %s" % datetime.fromtimestamp(start_time))
    try:
        main_loop(mesos, carbon, singularity)
    except (KeyboardInterrupt, SystemExit):
        print("Bye!")
        sys.exit(0)