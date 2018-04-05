"""
Compute amount of correct answer before first wrong answer.
"""

import argparse
import subprocess
import sys
import yaml

from datetime import datetime

import graph
import reader


class Analyzer:
    def __init__(self):
        pass


def get_statistics(responses: dict, dictionary: dict, now=0,
        postfix='') -> dict:
    """
    Getting statistics.

    Returns:
        Question of card with minimum planned time.
    """
    if now == 0:
        now = int((datetime.now() -
           datetime(1970, 1, 1)).total_seconds() / 60)

    minimum_time = None
    learned = 0
    not_learned = 0
    skipped = 0
    to_repeat = 0
    to_learn = 0
    score = 0
    added_today = 0
    heaviness = 0
    total_probability = 0

    for question in responses:
        if question not in dictionary:
            continue
        if not postfix and '#' in question:
            continue
        if postfix and not question.endswith(postfix):
            continue
        response = responses[question]
        if 'plan' in response:
            plan = response['plan']
            if 'last' in response:
                last = response['last']
                probability = 0.2 * (now - last) / (last - plan) + 1
            else:
                probability = 1
            if not minimum_time or plan < minimum_time:
                minimum_time = plan
            if plan <= now - 1:
                to_repeat += 1
            if 'answers' in response and plan < 1000000000:
                if response['answers'][-1] == 'y':
                    ys = len(response['answers']) - \
                        response['answers'].rfind('n') - 1
                    heaviness += 1.0 / (2.0 ** ys)
                    score += ys
                else:
                    heaviness += 1.0
            if plan >= 1000000000:
                skipped += 1
            elif 'answers' in response and response['answers'][-3:] == 'yyy' \
                    and response['plan'] > now:
                learned += 1
            else:
                not_learned += 1
        else:
            probability = 1
        total_probability += probability
        if 'added' in response:
            if int(response['added'] / 24 / 60) == int(now / 24 / 60):
                added_today += 1

    if not minimum_time:
        minimum_time = 0

    for question in dictionary:
        if not (question in responses):
            to_learn += 1
    return {'learned': learned, 'not_learned': not_learned, 'skipped': skipped,
        'to_repeat': to_repeat, 'to_learn': to_learn, 'score': score,
        'minimum_time': minimum_time, 'added_today': added_today,
        'heaviness': heaviness, 'probability': total_probability}


def count_responses(responses):
    a = 0
    for response in responses:
        if 'answers' in responses[response]:
            a += len(responses[response]['answers'])
    return a


def count_probability(responses):
    now = int((datetime.now() - datetime(1970, 1, 1)).total_seconds() / 60)
    probabilities = [0] * 100
    learning_words = 0
    learned_words = 0
    for_now = 0
    for question in responses:
        response = responses[question]
        if 'plan' in response and 'last' in response and 'answers' in response:
            last = float(response['last'])
            plan = float(response['plan'])
            if not response['answers'].endswith('y') or plan >= 1000000000:
                continue
            if plan < now:
                for_now += 1
            probability = 0.3 * (now - last) / (last - plan) + 1
            learning_words += 1
            learned_words += probability
            if probability < 0:
                probability = 0
            percent = int(probability * 100)
            if percent > 99:
                percent = 99
            probabilities[percent] += 1
    return probabilities, learning_words, learned_words, for_now


def count_heaviness(responses):
    now = int((datetime.now() - datetime(1970, 1, 1)).total_seconds() / 60)
    clicks = [0] * 100  # Prediction for 100 days
    for question in responses:
        if 'plan' in response and 'last' in response and 'answers' in response:
            last = float(response['last'])
            plan = float(response['plan'])
            if plan >= 1000000000:
                continue
            ys = len(response['answers']) - \
                response['answers'].rfind('n') - 1
    # TODO: implement


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Emmio user statistics analysis')
    parser.add_argument('-l', dest='learning_id', help='learning ID',
        required=True)
    parser.add_argument('-uf', dest='user_file_name',
        help='alternative user file name')
    parser.add_argument('--count-responses', dest='count_responses',
        help='count number of responses', action='store_true')
    options = parser.parse_args(sys.argv[1:])

    learning_id = options.learning_id

    config = yaml.load(open('config.yml'))

    if options.learning_id not in config['learnings']:
        print('Fatal: no learning with ID ' + options.learning_id + '.')
        sys.exit(1)

    learning_config = config['learnings'][options.learning_id]

    dictionary_id = learning_config['dictionary']
    user_id = learning_config['user']

    if dictionary_id not in config['dictionaries']:
        print('Fatal: no dictionary with ID ' + dictionary_id + '.')
        sys.exit(1)

    dictionary_config = config['dictionaries'][dictionary_id]

    if user_id not in config['users']:
        print('Fatal: no user with ID ' + user_id + '.')
        sys.exit(1)

    user_config = config['users'][user_id]

    if options.user_file_name:
        whole_answers = reader.read_answers_fast(options.user_file_name)
    else:
        whole_answers = reader.read_answers_fast(user_config['file'])

    whole_responses = {}
    for dictionary_user_id in whole_answers.keys():
        for question in whole_answers[dictionary_user_id]:
            whole_responses[dictionary_user_id + '_' + question] = \
                whole_answers[dictionary_user_id][question]

    responses = None
    for key in whole_answers:
        if key in dictionary_config['user_ids']:
            responses = whole_answers[key]
            break

    if options.count_responses:
        print(count_responses(responses))
        sys.exit(0)

    dictionary = reader.read_dict(dictionary_config['file'],
        dictionary_config['format'])

    probabilities, learning_words, learned_words, for_now = \
        count_probability(responses)

    now = int((datetime.now() - datetime(1970, 1, 1)).total_seconds() / 60)
    birth = int((datetime(1990, 7, 20) - datetime(1970, 1, 1)).total_seconds() / 60)

    statistics = get_statistics(responses, dictionary, now, '')
    print("All words:       %5d." % (statistics['learned'] + statistics['skipped']))
    print("Heaviness:       %.2f." % (statistics['heaviness']))
    print("Probability:   %7.1f." % (statistics['probability']))
    print("Added today:     %5d." % (statistics['added_today']))

    with open('statistics/' + learning_id + '/plan_time.dat', 'w+') as plan_time_file:
        for question in responses:
            response = responses[question]
            if 'plan' in response and response['plan'] < 1000000000:
                plan = response['plan']
                plan_time_file.write("%10.10f %5d\n" %
                    (int((plan - birth) / (60 * 24)) / 365.0,
                    (plan - now) % (60 * 24)))

    print("Learning words:  %5d." % learning_words)
    print("Learned words:   %5d." % learned_words)
    print("Forgotten words: %5d." % (learning_words - learned_words))
    print("For now:         %5d." % for_now)

    with open('statistics/' + learning_id + '/probability.dat', 'w+') as probability_file:
        for i in range(100):
            probability_file.write("%5d %5d\n" % (i, probabilities[i]))

    no_after_yes = {}
    yes_after_yes = {}
    no_after_all = {}
    yes_after_all = {}

    for k in range(100):
        no_after_yes[k] = 0
        yes_after_yes[k] = 0
        no_after_all[k] = 0
        yes_after_all[k] = 0

    for response in responses:
        if 'answers' in responses[response]:
            vector = responses[response]['answers']
            if len(vector) > 1:
                counter = 0
                yes_counter = 0
                for answer in vector:
                    if answer == 'y':
                        yes_after_yes[yes_counter] += 1
                        yes_after_all[counter] += 1
                        yes_counter += 1
                    else:
                        no_after_yes[yes_counter] += 1
                        no_after_all[counter] += 1
                        yes_counter = 0
                    counter += 1

    # print('''
    #  Amount of correct |
    #     answers before |
    #        first wrong | Cases
    # -------------------+-------''')

    failing = open('statistics/' + learning_id + '/fail_after_yes.dat', 'w+')
    for yes_before_no in no_after_yes:
        if no_after_yes[yes_before_no]:
            # print(' %17d | %4d %4d %7.2f %%' %
            #       (yes_before_no, no_after_yes[yes_before_no],
            #        yes_after_yes[yes_before_no],
            #        100 * no_after_yes[yes_before_no] / float(yes_after_yes[yes_before_no] + no_after_yes[yes_before_no])))
            failing.write('%d %d %d %f\n' %
                  (yes_before_no, no_after_yes[yes_before_no],
                   yes_after_yes[yes_before_no],
                   100 * no_after_yes[yes_before_no] / float(yes_after_yes[yes_before_no] + no_after_yes[yes_before_no])))
    failing.close()

    failing = open('statistics/' + learning_id + '/fail_after_all.dat', 'w+')
    for yes_before_no in no_after_all:
        if no_after_all[yes_before_no]:
            failing.write('%d %d %d %f\n' %
                  (yes_before_no, no_after_all[yes_before_no],
                   yes_after_all[yes_before_no],
                   100 * no_after_all[yes_before_no] / float(yes_after_all[yes_before_no] + no_after_all[yes_before_no])))
    failing.close()

    main_priority_id = learning_config['main_priority']

    if main_priority_id not in config['priorities']:
        print('Fatal: no such priority with ID ' + main_priority_id + '.')
        sys.exit(1)

    main_priority_config = config['priorities'][main_priority_id]

    priority_list = reader.read_priority(main_priority_config['file'])
    skip = []
    for word_priority in priority_list:
        word, priority = word_priority
        if "'" + word + "'" in responses:
            word = "'" + word + "'"
        if word in responses:
            if 'answers' in responses[word]:
                vector = responses[word]['answers']
                if vector == 'y':
                    skip.append(1)
                elif vector.startswith('n'):
                    skip.append(0)
            else:
                skip.append(1)
        elif word in dictionary:
            # print('Skipping stopped on ' + word)
            break

    # for k in priority_list:
    #     word, priority = k
    #     if word not in dictionary:
    #         print(word)

    # print(len(skip))
    skipping = open('statistics/' + learning_id + '/skipping.dat', 'w+')
    for i in range(len(skip) - 100):
        skipping.write(str(i) + ' ' + str(sum(skip[i:i + 100])) + '\n')
    # for i in range(1, len(skip)):
    #     skipping.write(str(i) + ' ' + \
    #         str(sum(skip[0:i]) / float(i) * 100.0) + '\n')
    skipping.close()

    user_data = responses

    try:
        graph.dump_times('statistics/' + learning_id + '/times.dat', user_data)
        graph.dump_times('statistics/' + learning_id + '/times_24.dat', user_data, scale=24)
        graph.dump_times_all('statistics/' + learning_id + '/times_all.dat', whole_responses)
        graph.dump_quality('statistics/' + learning_id + '/quality.dat', user_data)
        graph.dump_quality('statistics/' + learning_id + '/quality_sum.dat', user_data, is_sum=True)
    except Exception as e:
        print(e)
