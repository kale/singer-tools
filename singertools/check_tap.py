#!/usr/bin/env python3

import argparse
import attr
import singer
import subprocess
import sys
import subprocess
import threading
import tempfile
import json
import os
from terminaltables import AsciiTable
from subprocess import Popen

working_dir_name = 'singer-check-tap-data'

@attr.s
class StreamAcc(object):

    name = attr.ib()
    num_records = attr.ib(default=0)
    num_schemas = attr.ib(default=0)
    latest_schema = attr.ib(default=None, repr=False)


@attr.s
class OutputSummary(object):

    streams = attr.ib(default=attr.Factory(dict))
    num_states = attr.ib(default=0)
    
    def ensure_stream(self, stream_name):
        if stream_name not in self.streams:
            self.streams[stream_name] = StreamAcc(stream_name)
        return self.streams[stream_name]
    
    def add(self, message):
        if isinstance(message, singer.RecordMessage):
            self.ensure_stream(message.stream).num_records += 1

        elif isinstance(message, singer.SchemaMessage):
            self.ensure_stream(message.stream).num_schemas += 1

        elif isinstance(message, singer.StateMessage):
            self.latest_state = message.value
            self.num_states += 1

    def num_records(self):
        return sum([stream.num_records for stream in self.streams.values()])

    def num_schemas(self):
        return sum([stream.num_schemas for stream in self.streams.values()])    

    def num_messages(self):
        return self.num_records() + self.num_schemas() + self.num_states


class StdoutReader(threading.Thread):

    def __init__(self, process):
        self.process = process
        super().__init__()

    def run(self):
        self.summary = summarize_output(self.process.stdout)

    def finish_reading_logs(self):
        """Joins the thread with a timeout.

        Intended to be called on the parent thread.
        """
        print('Joining on thread {}'.format(self.name))
        self.join(timeout=5)
        if self.is_alive():
            print(
                'Thread {} did not finish within timeout'.format(self.name))
        else:
            print('Thread {} finished'.format(self.name))


def summarize_output(output):
    summary = OutputSummary()
    for line in output:
        summary.add(singer.parse_message(line))
    return summary


def print_summary(summary):

    print('The output is valid.')
    print('It contained {} messages for {} streams.'.format(summary.num_messages(), len(summary.streams)))
    print('')
    print('{:7} schema messages'.format(summary.num_schemas()))
    print('{:7} record messages'.format(summary.num_records()))
    print('{:7} state messages'.format(summary.num_states))
    print('')
    print('Details by stream:')
    headers = [['stream', 'records', 'schemas']]
    rows = [[s.name, s.num_records, s.num_schemas] for s in summary.streams.values()]
    data = headers + rows

    table = AsciiTable(data)
    print(table.table)


def run_and_summarize(tap, config, state=None):
    cmd = [tap, '--config', config]
    if state:
        cmd += ['--state', state]
    print('Running command {}'.format(cmd))
            
    tap = Popen(cmd,
                stdout=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True)
    summarizer = StdoutReader(tap)
    summarizer.start()
    tap.wait()
    return summarizer.summary


def check_with_no_state(args):
    return run_and_summarize(args.tap, args.config)


def check_with_state(args, state):
    state_path = os.path.join(working_dir_name, 'state.json')
    with open (state_path, mode='w') as state_file:
        json.dump(state, state_file)
    return run_and_summarize(args.tap, args.config, state_path)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        '-t',
        '--tap',
        help='Tap program to execute')
    
    parser.add_argument(
        '-c',
        '--config',
        help='Config file for tap')

    args = parser.parse_args()

    try:
        os.mkdir(working_dir_name)
    except FileExistsError:
        pass
    
    if args.tap:
        if not args.config:
            print('If you provide --taps you must also provide --config')
            exit(1)

    if args.tap:
        print('Checking tap {} with config {}'.format(args.tap, args.config))
        summary = check_with_no_state(args)
    else:
        print('Checking stdin for valid Singer-formatted data')
        summary = summarize_output(sys.stdin)

    print_summary(summary)

    if args.tap:
        if summary.latest_state:
            print('Now re-running tap with final state produced by previous run')
            summary = check_with_state(args, summary.latest_state)
            print_summary(summary)

if __name__ == '__main__':
    main()