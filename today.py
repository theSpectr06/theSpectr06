import datetime
from dateutil import relativedelta
import requests
import os
from lxml import etree
import time

HEADERS = {'authorization': 'token ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME']  # 'theSpectr06'
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'graph_commits': 0}

# Date your Arch install happened — uptime counts from here
ARCH_INSTALL_DATE = datetime.datetime(2025, 12, 21)  # adjust if needed


def arch_uptime():
    """
    Returns days since Arch was installed.
    e.g. '189 days'
    """
    diff = (datetime.datetime.today() - ARCH_INSTALL_DATE).days
    return '{} {}'.format(diff, 'day' if diff == 1 else 'days')


def format_plural(unit):
    return 's' if unit != 1 else ''


def simple_request(func_name, query, variables):
    request = requests.post(
        'https://api.github.com/graphql',
        json={'query': query, 'variables': variables},
        headers=HEADERS)
    if request.status_code == 200:
        return request
    raise Exception(func_name, 'failed with', request.status_code, request.text, QUERY_COUNT)


def graph_commits(start_date, end_date):
    """Total commits in a date range via contributionsCollection."""
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    variables = {'start_date': start_date, 'end_date': end_date, 'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    """Returns repo count, contributed repo count, or star count."""
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers { totalCount }
                        }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    data = request.json()['data']['user']['repositories']

    if count_type == 'repos':
        return data['totalCount']
    elif count_type == 'stars':
        stars = sum(node['node']['stargazers']['totalCount'] for node in data['edges'])
        if data['pageInfo']['hasNextPage']:
            stars += graph_repos_stars('stars', owner_affiliation, data['pageInfo']['endCursor'])
        return stars


def follower_getter(username):
    query_count('follower_getter')
    query = '''
    query($login: String!) {
        user(login: $login) { followers { totalCount } }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def user_getter(username):
    query_count('user_getter')
    query = '''
    query($login: String!) {
        user(login: $login) { createdAt }
    }'''
    request = simple_request(user_getter.__name__, query, {'login': username})
    return request.json()['data']['user']['createdAt']


def total_commits_all_time(acc_date):
    """
    Sum commits year-by-year from account creation.
    contributionsCollection only supports a 1-year window.
    """
    total = 0
    start = datetime.datetime.strptime(acc_date[:10], '%Y-%m-%d')
    now = datetime.datetime.utcnow()
    while start < now:
        end = min(start + relativedelta.relativedelta(years=1), now)
        total += graph_commits(
            start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            end.strftime('%Y-%m-%dT%H:%M:%SZ'))
        start = end
    return total


def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    start = time.perf_counter()
    result = funct(*args)
    return result, time.perf_counter() - start


def formatter(label, difference):
    print('{:<23}'.format('   ' + label + ':'), sep='', end='')
    if difference > 1:
        print('{:>12}'.format('%.4f' % difference + ' s '))
    else:
        print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = str(new_text)


def svg_overwrite(filename, uptime, commit_data, star_data, repo_data, contrib_data, follower_data):
    tree = etree.parse(filename)
    root = tree.getroot()
    find_and_replace(root, 'age_data',      uptime)
    find_and_replace(root, 'commit_data',   '{:,}'.format(commit_data))
    find_and_replace(root, 'star_data',     '{:,}'.format(star_data))
    find_and_replace(root, 'repo_data',     str(repo_data))
    find_and_replace(root, 'contrib_data',  str(contrib_data))
    find_and_replace(root, 'follower_data', str(follower_data))
    tree.write(filename, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    print('Calculation times:')

    acc_date, user_time      = perf_counter(user_getter, USER_NAME)
    formatter('account data', user_time)

    uptime = arch_uptime()
    print(f'   uptime:                    {uptime}')

    commit_data, commit_time = perf_counter(total_commits_all_time, acc_date)
    formatter('commits (all time)', commit_time)

    star_data,     star_time     = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    repo_data,     repo_time     = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    contrib_data,  contrib_time  = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

    formatter('stars',       star_time)
    formatter('repos',       repo_time)
    formatter('contributed', contrib_time)
    formatter('followers',   follower_time)

    svg_overwrite('dark.svg',  uptime, commit_data, star_data, repo_data, contrib_data, follower_data)
    svg_overwrite('light.svg', uptime, commit_data, star_data, repo_data, contrib_data, follower_data)

    print('\nTotal GitHub GraphQL API calls:', sum(QUERY_COUNT.values()))
    for funct_name, count in QUERY_COUNT.items():
        print('{:<28}'.format('   ' + funct_name + ':'), '{:>6}'.format(count))
