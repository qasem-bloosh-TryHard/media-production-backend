from celery import Celery
import time


celery_app=Celery("worker",broker="redis://cache:6379/0",backend="redis://cache:6379/0")

@celery_app.task
def process_heavy_video(video_name:str):
    print(f"start process video:{video_name}...")
    time.sleep(10)
    print("done")
    return "Success"
