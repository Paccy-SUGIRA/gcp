# /home/kench/Dev/gwiza-cash/gwizacash/scheduler.


import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

logger = logging.getLogger(__name__)
_scheduler = None

def reset_monthly_shares():
    try:
        call_command('reset_shares')
        logger.info("Monthly shares reset successfully.")
    except Exception as e:
        logger.error(f"Error resetting monthly shares: {str(e)}")

def distribute_monthly_profits():
    try:
        call_command('distribute_profits')
        logger.info("Monthly profit distribution completed.")
    except Exception as e:
        logger.error(f"Error distributing profits: {str(e)}")

def calculate_penalties():
    try:
        today = timezone.now().date()
        call_command('calculate_penalties', '--date', str(today))
        logger.info(f"Penalty calculation completed for {today}.")
    except Exception as e:
        logger.error(f"Error calculating penalties: {str(e)}")

def start_scheduler():
    if settings.DEBUG:
        logger.info("Scheduler not started in DEBUG mode.")
        return

    scheduler = BackgroundScheduler()

    # Reset monthly shares on 1st of each month at 02:00 AM
    scheduler.add_job(
        reset_monthly_shares,
        trigger=CronTrigger(day=1, hour=2, minute=0),
        id="reset_monthly_shares",
        max_instances=1,
        replace_existing=True,
    )

    # Distribute monthly profits on 2nd of each month at 03:00 AM
    scheduler.add_job(
        distribute_monthly_profits,
        trigger=CronTrigger(day=2, hour=3, minute=0),
        id="distribute_monthly_profits",
        max_instances=1,
        replace_existing=True,
    )

    # Calculate penalties **every day at 00:10 AM**
    scheduler.add_job(
        calculate_penalties,
        trigger=CronTrigger(hour=0, minute=10),
        id="calculate_penalties_daily",
        max_instances=1,
        replace_existing=True,
    )

    try:
        scheduler.start()
        logger.info("Scheduler started successfully.")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {str(e)}")
        scheduler.shutdown()
