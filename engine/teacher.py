"""
Emmio user interface.

Author: Sergey Vartanov (me@enzet.ru).
"""

import argparse
import sys
import yaml

from http.server import HTTPServer

import emmio
import server

parser = argparse.ArgumentParser()
parser.add_argument('-l', dest='learning_id')
parser.add_argument('--run-server', dest='is_server', action='store_true',
                    help='run web interface instead of console mode',
                    default=False)

arguments = parser.parse_args(sys.argv[1:])

usage = sys.argv[0] + ' -d <dictionary file name> -u <user name> <options>'

config = yaml.load(open('config.yml'))

if arguments.is_server:
    emmio_server = None
    try:
        handler = server.EmmioHandler
        emmio_server = HTTPServer(('', 8080), handler)

        handler.teachers = server.ServerTeachers(config)

        print('Emmio started on port %d.' % 8080)
        emmio_server.serve_forever()
    except KeyboardInterrupt:
        if emmio_server:
            emmio_server.socket.close()
else:
    teacher = emmio.Teacher(arguments.learning_id, config,
        options=vars(arguments))
    teacher.run()
