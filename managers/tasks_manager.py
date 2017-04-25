""" This module contains functionality, that is responsible for managing tasks """
import uuid
import json
import threading
import datetime
import pika

from black.black.db import sessions, Task


class ShadowTask(object):
    """ A shadow of the real task """
    def __init__(self, task_id, task_type, target, params, project_uuid, status=None, progress=None, text=None, date_added=datetime.datetime.utcnow(), stdout="", stderr=""):
        self.task_type = task_type
        self.target = target
        self.params = params
        self.project_uuid = project_uuid

        if task_id:
            self.task_id = task_id
        else:
            self.task_id = str(uuid.uuid4())

        self.status = status
        self.progress = progress
        self.text = text
        self.date_added = date_added
        self.stdout = stdout
        self.stderr = stderr

        self.channel = None

        # connect to the RabbitMQ broker
        credentials = pika.PlainCredentials('guest', 'guest')
        parameters = pika.ConnectionParameters('localhost', credentials=credentials)
        connection = pika.BlockingConnection(parameters)

        # Open a communications channel
        self.channel = connection.channel()
        self.channel.exchange_declare(
            exchange="tasks.exchange",
            exchange_type="direct",
            durable=True)
        self.channel.queue_declare(queue=self.task_type + "_tasks", durable=True)
        self.channel.queue_bind(
            queue=self.task_type + "_tasks",
            exchange="tasks.exchange",
            routing_key=self.task_type + "_tasks")

        self.channel.queue_declare(queue=self.task_type + "_notifications", durable=True)
        self.channel.queue_bind(
            queue=self.task_type + "_notifications",
            exchange="tasks.exchange",
            routing_key=self.task_type + "_notifications")


    def send_start_task(self):
        """ Put a message to the queue, which says "start my task, please """
        self.channel.basic_publish(exchange='',
                                   routing_key=self.task_type + "_tasks",
                                   body=json.dumps({
                                       'task_id': self.task_id,
                                       'target': self.target,
                                       'params': self.params,
                                       'project_uuid': self.project_uuid
                                   }))


    def set_status(self, new_status, progress, text, new_stdout, new_stderr):
        """ Change status, progress and text of the task """
        self.status = new_status
        self.progress = progress
        self.text = text
        self.stdout += new_stdout
        self.stderr += new_stderr

    def get_status(self):
        """ Returns a tuple of status, progress and text of the task"""
        return (self.status, self.progress, self.text)

    def get_as_native_object(self):
        """ "Serialize" the task to python native dict """
        return {
            "task_id" : self.task_id,
            "task_type" : self.task_type,
            "target" : self.target,
            "params" : self.params,
            "status" : self.status,
            "progress" : self.progress,
            "text" : self.text,
            "project_uuid" : self.project_uuid,
            # "stdout" : self.stdout,
            # "stderr" : self.stderr,
            "date_added": str(self.date_added)
        }

class TaskManager(object):
    """ TaskManager keeps track of all tasks in the system,
    exposing some interfaces for public use. """
    def __init__(self, data_updated_queue):
        self.data_updated_queue = data_updated_queue

        self.active_tasks = list()
        self.finished_tasks = list()

        self.update_from_db()

        self.channel = None

        # connect to the RabbitMQ broker
        credentials = pika.PlainCredentials('guest', 'guest')
        parameters = pika.ConnectionParameters('localhost', credentials=credentials)
        connection = pika.BlockingConnection(parameters)

        # Open a communications channel
        self.channel = connection.channel()
        self.channel.exchange_declare(
            exchange="tasks.exchange",
            exchange_type="direct",
            durable=True)

        self.channel.queue_declare(queue="tasks_statuses", durable=True)
        self.channel.queue_bind(
            queue="tasks_statuses",
            exchange="tasks.exchange",
            routing_key="tasks_statuses")

        self.channel.basic_consume(
            consumer_callback=self.parse_new_status,
            queue="tasks_statuses")

        thread = threading.Thread(target=self.channel.start_consuming)
        thread.start()

    def parse_new_status(self, channel, method, properties, message):
        """ Parse the message from the queue, which contains task status,
        updates the relevant ShadowTask and, we notify the upper module that
        it must update the scan results. """
        message = json.loads(message)
        task_id = message['task_id']

        for task in self.active_tasks:
            if task.task_id == task_id:
                new_status = message['status']
                task.set_status(new_status, message['progress'], message['text'], message['new_stdout'],
                    message['new_stderr'])

                if new_status == 'Finished' or new_status == 'Aborted':
                    self.active_tasks.remove(task)
                    self.finished_tasks.append(task)

                    # TODO: make more granular update request
                    self.data_updated_queue.put("scan")
                    self.data_updated_queue.put("file")

                break

        channel.basic_ack(delivery_tag=method.delivery_tag)

    def update_from_db(self):
        """ Extract all the tasks from the DB """
        session = sessions.get_new_session()
        tasks_from_db = session.query(Task).all()
        tasks = list(map(lambda x:
                         ShadowTask(task_id=x.task_id,
                                    task_type=x.task_type,
                                    target=json.loads(x.target),
                                    params=json.loads(x.params),
                                    project_uuid=x.project_uuid,
                                    status=x.status,
                                    progress=x.progress,
                                    text=x.text,
                                    date_added=x.date_added,
                                    stdout=x.stdout,
                                    stderr=x.stderr),
                         tasks_from_db))
        sessions.destroy_session(session)

        for task in tasks:
            status = task.get_status()[0]
            if status == 'Finished' or status == 'Aborted':
                self.finished_tasks.append(task)
            else:
                self.active_tasks.append(task)

    def get_tasks(self):
        """ Returns a list of active tasks and a list of finished tasks """
        return [self.active_tasks, self.finished_tasks]

    def get_tasks_native_objects(self):
        """ "Serializes" tasks to native python dicts """
        active = list(map(lambda x: x.get_as_native_object(), self.active_tasks))
        finished = list(map(lambda x: x.get_as_native_object(), self.finished_tasks))

        return {
            'active': active, 
            'finished': finished
        }

    def create_task(self, task_type, target, params, project_uuid):
        """ Register the task and send a command to start it """
        task = ShadowTask(task_id=None,
                          task_type=task_type,
                          target=target,
                          params=params,
                          project_uuid=project_uuid)
        task.send_start_task()
        self.active_tasks.append(task)

        return task.get_as_native_object()
