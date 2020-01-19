# -*- coding: utf-8 -*- from __future__ import unicode_literals

import urllib
import html
import os
import shutil
import subprocess
import hashlib

from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from emmio import emmio
from emmio import graph
from emmio import network

PORT_NUMBER = 8080


class ServerTeachers:
    def __init__(self, config: dict):
        self.teachers = {}
        self.config = config
        for learning_id in config['learnings']:
            teacher = emmio.Teacher(learning_id, config, {})
            self.teachers[learning_id] = teacher


class EmmioHandler(BaseHTTPRequestHandler):

    teachers = None

    @staticmethod
    def to_HTML(answer):
        answer = answer.replace(' ', '&nbsp;')
        answer = answer.replace('\n', '<br />')

        answer = answer.replace('_a.', '<span class=form>прил.</span>')
        answer = answer.replace('_adv.', '<span class=form>нар.</span>')
        answer = answer.replace('_attr.', '<span class=form>attr.</span>')
        answer = answer.replace('_cj.', '<span class=form>союз</span>')
        answer = answer.replace('_comp.', '<span class=form>ср. ст.</span>')
        answer = answer.replace('_conj.', '<span class=form>с. мест.</span>')
        answer = answer.replace('_demonstr.', '<span class=form>указ. мест.</span>')
        answer = answer.replace('_emph.', '<span class=form>усилит. мест.</span>')
        answer = answer.replace('_f.', '<span class=form>ж. р.</span>')
        answer = answer.replace('_imp.', '<span class=form>повелит. накл.</span>')
        answer = answer.replace('_impers.', '<span class=form>безлич. ф.</span>')
        answer = answer.replace('_indef.', '<span class=form>неопр. мест.</span>')
        answer = answer.replace('_inf.', '<span class=form>неопр. ф. гл.</span>')
        answer = answer.replace('_inter.', '<span class=form>вопр. мест.</span>')
        answer = answer.replace('_interj.', '<span class=form>межд.</span>')
        answer = answer.replace('_invar.', '<span class=form>неизм.</span>')
        answer = answer.replace('_m.', '<span class=form>м. р.</span>')
        answer = answer.replace('_mis.', '<span class=form>неправ.</span>')
        answer = answer.replace('_n-card.', '<span class=form>колич. числит.</span>')
        answer = answer.replace('_n.', '<span class=form>сущ.</span>')
        answer = answer.replace('_n-ord.', '<span class=form>порядк. числит.</span>')
        answer = answer.replace('_neg.', '<span class=form>отриц.</span>')
        answer = answer.replace('_obj.', '<span class=form>косв. п.</span>')
        answer = answer.replace('_p-p.', '<span class=form>прич. прош. вр.</span>')
        answer = answer.replace('_pres-p.', '<span class=form>прич. наст. вр.</span>')
        answer = answer.replace('_p.', '<span class=form>прош.</span>')
        answer = answer.replace('_pass.', '<span class=form>страдат. залог</span>')
        answer = answer.replace('_pers.', '<span class=form>личн. мест.</span>')
        answer = answer.replace('_pf.', '<span class=form>сов. вид</span>')
        answer = answer.replace('_pl.', '<span class=form>мн. ч.</span>')
        answer = answer.replace('_poss.', '<span class=form>притяж. мест.</span>')
        answer = answer.replace('_predic.', '<span class=form>predic.</span>')
        answer = answer.replace('_pref.', '<span class=form>прист.</span>')
        answer = answer.replace('_prep.', '<span class=form>пред.</span>')
        answer = answer.replace('_pres.', '<span class=form>наст. вр.</span>')
        answer = answer.replace('_pron.', '<span class=form>мест.</span>')
        answer = answer.replace('_recipr.', '<span class=form>вз. мест.</span>')
        answer = answer.replace('_refl.', '<span class=form>уп. с возвр. мест.</span>')
        answer = answer.replace('_rel.', '<span class=form>отн. мест.</span>')
        answer = answer.replace('_sg.', '<span class=form>ед. ч.</span>')
        answer = answer.replace('_subj.', '<span class=form>им. п.</span>')
        answer = answer.replace('_sup.', '<span class=form>прев. ст.</span>')
        answer = answer.replace('_v.', '<span class=form>гл.</span>')

        answer = answer.replace('т.п.', 'т. п.')
        answer = answer.replace('т.д.', 'т. д.')
        return answer

    def write(self, message):
        if isinstance(message, bytes):
            self.wfile.write(message)
        else:
            self.wfile.write(message.encode('utf-8'))

    @staticmethod
    def format_time(minutes):
        result = ''
        if int(minutes / 60 / 24):
            result += str(int(minutes / 60 / 24)) + ' d '
        minutes -= 60 * 24 * int(minutes / 60 / 24)
        if int(minutes / 60):
            result += str(int(minutes / 60)) + ' h '
        minutes -= 60 * int(minutes / 60)
        if minutes:
            result += str(minutes) + ' min '
        return result[:-1]

    def do_GET(self):
        for k in [['css', 'text/css'],
                ['svg', 'image/svg+xml'],
                ['png', 'image/png'],
                ['jpg', 'image/jpg'],
                ['ico', 'image/ico'],
                ['ogg', 'audio/ogg']]:
            if self.path.endswith('.' + k[0]):
                try:
                    f = open('' + self.path[1:], 'rb')
                    self.send_response(200)
                    self.send_header('Content-type', k[1])
                    self.end_headers()
                    self.write(f.read())
                    f.close()
                except Exception as e:
                    print(e)
                return

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset = utf-8')
        self.end_headers()

        arguments = {}
        if '?' in self.path:
            args = self.path.split('?')[1].split('&')
            for arg in args:
                arguments[arg.split('=')[0]] = \
                    urllib.parse.unquote(arg.split('=')[1])

        learning_id = None
        if 'learning_id' in arguments:
            learning_id = arguments['learning_id']

        now = int((datetime.now() - datetime(1970, 1, 1)).total_seconds() / 60)

        counter = 0

        output = html.HTML(css='simple', icon='favicon.png')

        # Processing.

        if learning_id:
            teacher = self.teachers.teachers[learning_id]
            if self.path.startswith('/response'):
                response = arguments['response'] == 'yes'
                question = arguments['question']
                scheme_id = arguments['scheme_id']
                teacher.process_user_response(response, question, now,
                    scheme_id)

            # Header.

            output.add(html.Div(
                html.Image('logo.svg', id='logo', height='20px'),
                'logo'))

        language_tabs = []

        for current_learning_id in sorted(self.teachers.config['learnings']):
            language_tab = []
            current_teacher = self.teachers.teachers[current_learning_id]
            per_day = current_teacher.per_day
            current_statistics = current_teacher.get_statistics()
            if current_learning_id == learning_id:
                language_tab.append(html.Text(current_teacher.learning_name))
            else:
                language_tab.append(
                    html.A(
                        '/show_question?learning_id=' + current_learning_id,
                        html.Text(current_teacher.learning_name)))
            language_tab.append(html.Div(
                html.Text(str(current_statistics['to_repeat'])), 'to_repeat'))
            if per_day:
                language_tab.append(html.Div(html.Text(
                    str(per_day - current_statistics['added_today'])), 'per_day'))
            language_tab.append(html.Div(
                html.Text(str(current_statistics['learned'] +
                    current_statistics['skipped'])), 'known'))
            counter += current_statistics['to_repeat']
            language_tabs.append(html.Div(language_tab, 'language_tab'))

        output.add(html.Div(language_tabs, 'language_tabs'))

        title = ''
        if counter:
            title += '(' + str(counter) + ') '
        title += 'Emmio'

        output.set_title(title)

        # Subheader.

        submenu_items = []

        if self.path.startswith('/show_question') or \
                self.path.startswith('/response'):
            submenu_items.append(
                html.Div(html.Text('Learning'), 'submenu_item'))
        else:
            submenu_items.append(
                html.Div(html.A('/show_question?learning_id=' +
                    learning_id, html.Text('Learning')), 'submenu_item'))

        if self.path.startswith('/statistics'):
            submenu_items.append(
                html.Div(html.Text('Statistics'), 'submenu_item'))
        else:
            submenu_items.append(
                html.Div(html.A('/statistics?learning_id=' + learning_id, html.Text('Statistics')), 'submenu_item'))

        output.add(html.Div(submenu_items, 'submenu'))

        if self.path.startswith('/statistics'):
            teacher = self.teachers.teachers[learning_id]
            try:
                os.makedirs('statistics/' + learning_id)
            except OSError:
                pass
            graph.dump_times('statistics/' + learning_id + '/times.dat',
                teacher.user_data)

            original_directory = os.getcwd()
            shutil.copyfile('statistics.gnuplot', 'statistics/' + learning_id + '/statistics.gnuplot')
            os.chdir('statistics/' + learning_id)
            try:
                process_output = subprocess.check_output(['gnuplot', 'statistics.gnuplot'])
                print(process_output)
            except subprocess.CalledProcessError as e:
                print(e)
            os.chdir(original_directory)

            output.add(html.Image('statistics/' + learning_id + '/times.svg'))
            self.write(output.to_html())
            return

        # Refresh mode.

        if learning_id:
            if self.path.startswith('/show_question'):
                output.set_refresh(60)
            if self.path.startswith('/response'):
                output.set_refresh(60, '/show_question?learning_id=' +
                    learning_id)

            # Body.

            teacher = self.teachers.teachers[learning_id]
            statistics = teacher.get_statistics()

            statistics_items = []

            statistics_items.append(
                html.Div(html.Text("Learned"), 'statistics_key'))
            statistics_items.append(html.Div(
                html.Text(str(statistics['learned'])), 'statistics_value'))

            output.add(html.Div(statistics_items, 'statistics'))

            empty_div = html.Div([html.Text('&nbsp;')], 'empty_button')

            if self.path.startswith('/show_question') or \
                    self.path.startswith('/response'):

                new_question, is_new, scheme_id = teacher.get_next_question(now)
                break_time = statistics['minimum_time'] - now + 1

                scheme = None
                for current_scheme in teacher.schemes:
                    if current_scheme['id'] == scheme_id:
                        scheme = current_scheme
                        break

                if not new_question or (is_new and teacher.per_day and
                        statistics['added_today'] >= teacher.per_day):
                    output.add(
                        html.Div(
                            html.Div(
                                html.Text('Question for repeat in ' +
                                    self.format_time(break_time) + '.'),
                                'nothing'),
                            'learning_block'))

                    output.add(html.Div([empty_div, empty_div], 'control'))
                else:
                    learning_block = html.Div([], 'learning_block')

                    question_text = teacher.get_element_text(new_question,
                        scheme['question'])

                    if scheme['question']['type'] == 'text':
                        question_text = self.to_HTML(question_text)

                    learning_block.add(html.Div(
                        html.Text(question_text),
                        'question_' + scheme['question']['type']))

                    if is_new:
                        learning_block.add(html.Div(html.Text('new question'),
                            'new_question_label'))

                        learning_block.add(html.Div(
                            html.Text('Question for repeat in ' +
                                self.format_time(break_time) + '.'),
                            'nothing'))

                    if learning_id in ['enzet_english', 'enzet_french']:
                        learning_block.add(html.Div([], 'audio_box'))

                    output.add(learning_block)

                    show_div = html.A(
                        '/show_answer?question=' + new_question + '&learning_id=' + learning_id + '&scheme_id=' +
                        scheme_id,
                        html.Div(html.Text('Show answer'), 'button', 'show_answer'))
                    output.add(
                        html.Div([show_div, empty_div], 'control'))
                    output.set_script('''
                    document.addEventListener('keydown', (event) => {
                        const keyName = event.key;
                        if (keyName == 'j') {
                            window.location.href = "/show_answer?question=''' + new_question +
                                      '''&learning_id=''' + learning_id + '''&scheme_id=''' + scheme_id + '''";
                            button = document.getElementById("show_answer");
                            button.style.backgroundColor = "rgba(0, 0, 0, 0.3)";
                        }
                    }, false);
                    ''')

            if self.path.startswith('/show_answer'):
                question = arguments['question']
                scheme_id = arguments['scheme_id']
                answer = teacher.get_answer(question)

                scheme = None
                for current_scheme in teacher.schemes:
                    if current_scheme['id'] == scheme_id:
                        scheme = current_scheme
                        break

                learning_block = html.Div([], 'learning_block')

                question_text = \
                    teacher.get_element_text(question, scheme['question'])

                if scheme['question']['type'] == 'text':
                    question_text = self.to_HTML(question_text)

                learning_block.add(html.Div(
                    html.Text(question_text),
                    'question_' + scheme['question']['type']))

                if learning_id in ['enzet_english', 'enzet_french']:

                    m = hashlib.md5()
                    if learning_id == 'enzet_english':
                        file_name = 'En-us-' + question + '.ogg'
                    elif learning_id == 'enzet_french':
                        file_name = 'Fr-' + question + '.ogg'
                    m.update(file_name.encode('utf-8'))
                    hash_code = m.hexdigest()
                    audio_link = 'upload.wikimedia.org/wikipedia/commons/' + \
                        hash_code[0] + '/' + hash_code[:2] + '/' + file_name
                    audio_link = urllib.parse.quote(audio_link)
                    audio_file_name = network.get_file_name(audio_link, [],
                        'cache/' + file_name, is_secure=True)

                    if audio_file_name and \
                            os.stat(audio_file_name).st_size > 1000:
                        learning_block.add(html.Div(html.Audio(audio_file_name),
                            'audio_box'))
                    else:
                        learning_block.add(html.Div(html.Text('No audio.'),
                            'audio_box'))

                for answer_format in scheme['answer']:
                    if answer_format['source'] == 'key':
                        answer_text = question
                    elif answer_format['source'] == 'value':
                        answer_text = teacher.get_answer(question)
                    elif answer_format['source'] == 'dict_value':
                        answer_text = teacher.get_answer_key(question,
                            answer_format['field'])
                    else:
                        answer_text = question

                    if answer_format['type'] == 'text':
                        answer_text = self.to_HTML(answer_text)

                    learning_block.add(html.Div(
                        html.Text(answer_text),
                        'answer_' + answer_format['type']))

                m = hashlib.md5()
                file_name = question[0].upper() + question[1:] + '.jpg'
                m.update(file_name.encode('utf-8'))
                hash_code = m.hexdigest()
                image_link = 'https://upload.wikimedia.org/wikipedia/commons/' + hash_code[0] + '/' + hash_code[:2] + '/' + file_name

                # learning_block.add(html.Div(
                #     html.Image(image_link, id='illustration'), 'illustration'))

                output.add(learning_block)

                know_div = html.A(
                    '/response?question=' + question + '&learning_id=' +
                    learning_id + '&response=yes&scheme_id=' + scheme_id,
                    html.Div(html.Text('Know'), 'button', 'know'))
                dont_know_div = html.A(
                    '/response?question=' + question + '&learning_id=' +
                    learning_id + '&response=no&scheme_id=' + scheme_id,
                    html.Div(html.Text('Don\'t know'), 'button', 'dont_know'))
                output.add(html.Div([know_div, dont_know_div], 'control'))
                output.set_script('''
                document.addEventListener('keydown', (event) => {
                    const keyName = event.key;
                    if (keyName == 'j') {
                        window.location.href = "/response?question=''' + question +
                                  '''&learning_id=''' + learning_id + '''&response=yes&scheme_id=''' + scheme_id + '''";
                        button = document.getElementById("know");
                        button.style.backgroundColor = "rgba(0, 0, 0, 0.3)";
                    } else if (keyName == 'k') {
                        window.location.href = "/response?question=''' + question +
                                  '''&learning_id=''' + learning_id + '''&response=no&scheme_id=''' + scheme_id + '''";
                        button = document.getElementById("dont_know");
                        button.style.backgroundColor = "rgba(0, 0, 0, 0.3)";
                    }
                }, false);
                ''')

        self.write(output.to_html())
        # self.flush_headers()
        # self.finish()

        # Write.

        if learning_id:
            teacher = self.teachers.teachers[learning_id]
            if self.path.startswith('/response'):
                teacher.write_data()

    '''
    def do_get_1(self):

        for k in [['css', 'text/css'],
                ['svg', 'image/svg+xml'],
                ['png', 'image/png'],
                ['ico', 'image/ico']]:
            if self.path.endswith('.' + k[0]):
                try:
                    f = open('' + self.path[1:], 'rb')
                    self.send_response(200)
                    self.send_header('Content-type', k[1])
                    self.end_headers()
                    self.write(f.read())
                    f.close()
                except Exception as e:
                    print(e)
                return

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset = utf-8')
        self.end_headers()

        self.write('<html><head>')
        self.write('<meta http-equiv = "Content-Type" content = "text/html; charset = utf-8">')
        self.write('<link rel = "stylesheet" href = "simple.css">')
        self.write('</head><body>')

        postfix = '' if self.scheme == [1, 2] else '#' + str(self.scheme[0]) + '#' + str(self.scheme[1])
        action = None

        if self.path == '/':
            action = 'show_question'
        elif not (self.path.startswith('/emmio')):
            print('Error path:', self.path)
            return
        else:
            arguments = self.path.split('?')[1].split('&')
            for argument in arguments:
                pair = argument.split('=')
                if pair[0] == 'action':
                    action = pair[1]
                elif pair[0] == 'question':
                    question = urllib.parse.unquote(pair[1])
                    # question = pair[1].replace('%20', ' ')\
                    #     .replace('%C3%9F', 'ß')\
                    #     .replace('%C3%A4', 'ä')\
                    #     .replace('%C3%B6', 'ö')\
                    #     .replace('%C3%BC', 'ü')

        if action in ['write']:
            self.full_user_data[self.dictionary_name] = self.user_data
            self.teacher.write_data(self.full_user_data, self.user_name)

        self.write('<a href="emmio?action=write"><div class=black_button>Save</div></a>\n')

        now = int((datetime.now() - datetime(1970, 1, 1)).total_seconds() / 60)
        statistics = analysis.get_statistics(self.user_data, self.cards, now,
            postfix)

        time_to_repeat = statistics['minimum_time'] - now + 1
        if time_to_repeat > 0:
            self.write('<div>Next word for repeat in ' + str(statistics['minimum_time'] - now + 1) + ' min.</div>')
        self.write('<div class=outer><div class=statistics>')
        for element in [['learned', statistics['learned']], ['score', statistics['score']], ['today', statistics['added_today']]]:
            self.write('<div class=stat_key>' + str(element[0]) + '</div><div class=stat_value>' + str(element[1]) + '</div>')
        self.write('</div></div>\n')

        self.write('<div class=outer>')
        self.write('<div class=now>' + str(statistics['to_repeat']) + '</div>')
        self.write('</div>')

        if action in ['show_question', 'know', 'dont_know', 'write']:
            if action in ['know', 'dont_know']:
                now = int((datetime.now() - datetime(1970, 1, 1))
                    .total_seconds() / 60)
                current = self.user_data[question + postfix] \
                    if ((question + postfix) in self.user_data) else {}
                response = action == 'know'
                self.teacher.process_user_response(response, current, now)
                self.user_data[question + postfix] = current

            now = int((datetime.now() - datetime(1970, 1, 1))
                .total_seconds() / 60)
            statistics = analysis.get_statistics(self.user_data, self.cards,
                now, postfix)

            if statistics['to_repeat'] > 0 or statistics['to_learn'] > 0:
                next_question, is_new_card = \
                    self.teacher.get_next_question(self.user_data, self.cards,
                        now, self.priority_list, postfix)
            if not(next_question is None):
                question = self.cards[next_question][self.scheme[0] - 2] \
                    if (self.scheme[0] != 1) else next_question
                current = self.user_data[next_question + postfix] \
                    if ((next_question + postfix) in self.user_data) else {}
                self.write('<div class=outer>'
                    '<a href="emmio?action=show_answer&question=' +
                    next_question + '"><div class=button>Show answer</div>'
                    '</a></div>')
                if is_new_card:
                    self.write('<div class=outer_main>'
                        '<div class=new_question>' + question +
                        '</div></div>\n')
                else:
                    self.write('<div class=outer_main><div class=question>' +
                        question + '</div></div>\n')
            else:
                break_time = statistics['minimum_time'] - now + 1
                self.write('<div>Take a break for ' + str(break_time) +
                    ' min.</div>')
                self.write('<script type = "text/javascript">'
                    'location.replace("emmio?action=wait");</script>')
                self.write('<meta http-equiv="refresh" content="5" '
                    'url="emmio?action=wait">')
        elif action in ['show_answer']:
            # answer = self.cards[question][self.scheme[1] - 2] \
            #     if (self.scheme[1] != 1) else question
            answer = self.cards[question]
            answer = self.answer_to_HTML(answer)
            self.write('<div class=outer><a href="emmio?action=know&question=' + question + '"><div class=button>Know</div></a> ')
            self.write('<a href="emmio?action=dont_know&question=' + question + '"><div class=button>Don\'t</div></a></div>')
            self.write('<div class=outer_main>')
            self.write('<div class=question>' + question + '</div>')
            self.write('<div class=answer>' + answer + '</div>')
            self.write('</div>\n')
        elif action in ['wait']:
            break_time = statistics['minimum_time'] - now + 1
            self.write('<div>Take a break for ' + str(break_time) + ' min.</div>')
            if break_time > 0:
                self.write('<meta http-equiv="refresh" content="5" url="emmio?action=wait">')
            else:
                self.write('<meta http-equiv="refresh" content="5" url="emmio?action=show_question">')
        else:
            self.write('<div class=button><a href="emmio?action=show_question">Start</a></div>')

        #self.write(
        <table>
            <tr>
                <td colspan=2>
                    <embed width=600px height=400px type="image/svg+xml" src="times.svg" />
                </td>
            </tr>
            <tr>
                <td>
                    <embed type="image/svg+xml" src="quality.svg" />
                </td>
                <td>
                    <embed type="image/svg+xml" src="quality_sum.svg" />
                </td>
            </tr>
        </table>

        try:
            graph.dump_times('times.dat', self.user_data)
            graph.dump_quality('quality.dat', self.user_data)
            graph.dump_quality('quality_sum.dat', self.user_data, is_sum=True)
            subprocess.check_output(['gnuplot', 'statistics.gnuplot'])
        except Exception as e:
            print(e)

        return
        '''
