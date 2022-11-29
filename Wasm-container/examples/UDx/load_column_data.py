#!/usr/bin/env python
"""
python load_column_data.py rows columns

Load a table (Trows_columns) with rows rows of columns data-elements
All columns are type int

If your table is huge, this program is not very fast, I'm afraid.
"""

import argparse
import random
import sys
import vertica_python

DEFAULT_SEED = 3141592

def tdecl(typechar, colsize):
    if typechar == 'i': return 'int'
    elif typechar == 'v': return f'varchar({colsize})'
    else: raise ValueError(f'called with typechar "{typechar}"')

class data_generator:
    """
    A file-like object to generate data for a COPY ... FROM stdin 
    """
    def __init__(self, rows, cols, coltype='i', colsize=1):
        self.output_row = 0
        self.rows = rows
        self.cols = cols
        self.coltype = coltype
        self.colsize = colsize
        # invariant: self.buffer always terminates with a complete row
        self.buffer = ""

    def read(self, size=-1):
        if size == 0 or self.output_row > self.rows:
            return 0
        while len(self.buffer) < size and self.output_row < self.rows:
            rowdata = []
            for coltype in self.coltype:
                if coltype == 'i':
                    rowdata.append(random.randint(0, 10_000))
                else:
                    rowdata.append(generate_varchar(self.colsize))
            self.buffer += (', '.join(map(str, rowdata)) + "\n")
            self.output_row += 1
        # This may be a lot of copying
        retval = self.buffer[:size]
        self.buffer = self.buffer[size:]
        return retval

conn_info = {'host': '127.0.0.1',
             'port': 5433,
             # 'user': 'dbadmin',
             'user': 'dmankins',
             # 'password': 'some_password',
             'database': 'verticadb21150',
             # autogenerated session label by default,
             # 'session_label': 'some_label',
             # default throw error on invalid UTF-8 results
             'unicode_error': 'strict',
             # SSL is disabled by default
             'ssl': False,
             # autocommit is off by default
             'autocommit': True,
             # using server-side prepared statements is disabled by default
             'use_prepared_statements': True,
             # connection timeout is not enabled by default
             # 5 seconds timeout for a socket operation (Establishing a TCP connection or read/write operation)
             # 'connection_timeout': 60
             }

def stringify(big_int: int) -> str:
    """
    Turn a big number into an abbreviated number name (e.g., 1_000 -> 1K, 1_000_000 -> 1M
    """
    if(int(big_int) >= 1_000_000): return f'{big_int//1_000_000}M'
    if(int(big_int) >= 1_000): return f'{big_int//1_000}K'
    return f'{big_int}'

def parse_args(argv):
    parser = argparse.ArgumentParser("Generate a table with columns of a single type")
    parser.add_argument('-c', '--cols', action='store', dest='colcount', type=int,
                        default=1, help='specify column count (default 1)')
    parser.add_argument('--colnames', action='store', dest='colnames', type=str,
                        default='', help='specify column names (if not using the default) --- one string, separated by commas')
    parser.add_argument('-d', '--dbname', action='store', dest='dbname', type=str,
                        help='specify database name')
    parser.add_argument('-n', '--name', action='store', dest='table_name', type=str,
                        default='', help='specify the name for the table, if not using the defaul)')
    parser.add_argument('-p', '--prefix', action='store', dest='table_prefix', type=str,
                        default='T', help='specify the prefix for the table name (e.g., "TFunc", "SFunc")')
    parser.add_argument('-P', '--Port', action='store', dest='dbport', type=int,
                        help='specify the VSQL port number')
    parser.add_argument('--partition', action='store', dest='partition', type=str,
                        default='', help='specify a partition statement (argument string in quotes)')
    parser.add_argument('-r', '--rows', action='store', dest='rowcount', type=int,
                        default=100_000, help='specify rowcount (default 10^5')
    parser.add_argument('-s', '--size', action='store', dest='colsize', type=int,
                        default=32, help='specify size for varchar cols (default 32)')
    parser.add_argument('--seed', action='store', dest='seed', type=int,
                        default=DEFAULT_SEED, help=f'specify random seed (default: {DEFAULT_SEED}, -1 means no seed)')
    parser.add_argument('-t', '--type', action='store', dest='coltype', type=str,
                        default='int',
                        help='specify type for all cols (default: int; choices: {int, varchar, string-of-i-and-v}')
    parser.add_argument('-U', '--User', action='store', dest='dbuser', type=str,
                        default='dbadmin', help=f'specify the DB user name (default: dbadmin)')
    return parser.parse_args(argv)

alphabet = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" 
def generate_varchar(size):
    """
    generate a varchar of a given maximum size
    """
    # TODO maybe randomizing the size is a complication
    # TODO Random construction like this does not lend itself to
    # compression --- does that matter?
    size_choice = random.randint(min(1, size), max(1, size))
    letters = []
    for i in range(size_choice):
        letters.append(random.choice(alphabet))
    return ''.join(['"', ''.join(letters), '"'])
    # return ''.join(letters)


def main(argv):
    args = parse_args(argv[1:])

    if args.seed < 0:
        random.seed(None)
    else:
        random.seed(args.seed)

    rows = args.rowcount
    columns = args.colcount

    if args.dbport:
        conn_info['port'] = args.dbport
        
    if args.dbuser:
        conn_info['user'] = args.dbuser

    if args.dbname:
        conn_info['database'] = args.dbname

    if args.coltype == 'varchar':
        typestr = f'varchar({args.colsize})'
        typestr_for_table_name = f'v{stringify(args.colsize)}'
    elif args.coltype == 'int':
        typestr = 'int'
        typestr_for_table_name = 'i'
    else:
        if args.table_name == '':
            raise ValueError('If using "viivi" style types, must specify table name')
        typestr = args.coltype
        
    if args.partition != '':
        partition_by = f'partition by ({args.partition})'
    else:
        partition_by = ''

    # I hate counting 0s, so abbreviate big numbers
    if args.table_name == '':
        table_name = f'{args.table_prefix}{stringify(columns)}{typestr_for_table_name}'
    else:
        table_name = args.table_name

    colsize = args.colsize

    column_names = []
    column_decls = []

    if args.colnames != '':
        colnames = args.colnames.split(',')
        for cname, ctype in zip(colnames, typestr):
            column_decls.append(f'{cname} {tdecl(ctype, colsize)}')
            column_names.append(f'{cname}')
    else:
        cnames = range(columns)
        for cname, ctype in zip(cnames, typestr):
            column_decls.append(f'c{cname} {tdecl(ctype, colsize)}')
            column_names.append(f'c{cname}')

    column_decl = '( ' + ', '.join(column_decls) + ')'
    column_value_list = '( ' + ', '.join(column_names) + ' )'

    data_source = data_generator(rows, columns, typestr, colsize)

    with vertica_python.connect(**conn_info) as conn:
        cur = conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS {table_name} CASCADE')
        cur.execute(f'CREATE TABLE {table_name} {column_decl} {partition_by}')
        try:
            typestr.index('v')
            cur.copy(f"COPY {table_name}{column_value_list} FROM stdin DELIMITER ',' ENCLOSED BY '\"' ", data_source)
        except ValueError:
            cur.copy(f"COPY {table_name}{column_value_list} FROM stdin DELIMITER ',' ", data_source)

if __name__ == '__main__':
    main(sys.argv)
