from flask import render_template, flash, redirect, url_for, request, send_from_directory, Markup
from app.forms import LoginForm, RegistrationForm, EmptyForm, SearchForm, ChannelForm
from app.models import User, twitterPost, ytPost, Post, youtubeFollow, twitterFollow
from flask_login import login_user, logout_user, current_user, login_required
from flask import Flask, Response, stream_with_context
from requests_futures.sessions import FuturesSession
from concurrent.futures import as_completed
from werkzeug.utils import secure_filename
from youtube_search import YoutubeSearch
from werkzeug.urls import url_parse
from youtube_dl import YoutubeDL
from bs4 import BeautifulSoup
from app import app, db
import random, string
import time, datetime
import feedparser
import requests
import json
import re

# Instances - Format must be instance.tld (No '/' and no 'https://')
nitterInstance = "https://nitter.net/"
nitterInstanceII = "https://nitter.mastodont.cat/"

ytChannelRss = "https://www.youtube.com/feeds/videos.xml?channel_id="
invidiousInstance = "invidio.us"

##########################
#### Global variables ####
##########################
ALLOWED_EXTENSIONS = {'json'}

#########################
#### Twitter Logic ######
#########################
@app.route('/')
@app.route('/index')
@login_required
def index():
    start_time = time.time()
    followingList = current_user.twitter_following_list()
    followCount = len(followingList)
    posts = []
    avatarPath = "img/avatars/1.png"
    form = EmptyForm()
    posts.extend(getFeed(followingList))
    posts.sort(key=lambda x: x.timeStamp, reverse=True)
    if not posts:
        profilePic = avatarPath
    else:
        profilePic = posts[0].userProfilePic
    print("--- {} seconds fetching twitter feed---".format(time.time() - start_time))
    return render_template('index.html', title='Home', posts=posts, avatar=avatarPath, profilePic = profilePic, followedCount=followCount, form=form)

@app.route('/savePost/<url>', methods=['POST'])
@login_required
def savePost(url):
    savedUrl = url.replace('~', '/')
    r = requests.get(savedUrl)
    html = BeautifulSoup(str(r.content), "lxml")
    post = html.body.find_all('div', attrs={'class':'tweet-content'})

    newPost = Post()
    newPost.url = savedUrl
    newPost.body = html.body.find_all('div', attrs={'class':'main-tweet'})[0].find_all('div', attrs={'class':'tweet-content'})[0].text
    newPost.username = html.body.find('a','username').text.replace("@","")
    newPost.timestamp = html.body.find_all('p', attrs={'class':'tweet-published'})[0].text
    newPost.user_id = current_user.id
    try:
        db.session.add(newPost)
        db.session.commit()
    except:
        flash("Post could not be saved. Either it was already saved or there was an error.")
    return redirect(url_for('index'))

@app.route('/saved')
@login_required
def saved():
    savedPosts = current_user.saved_posts().all()
    return render_template('saved.html', title='Saved', savedPosts=savedPosts)

@app.route('/deleteSaved/<id>', methods=['POST'])
@login_required
def deleteSaved(id):
    savedPost = Post.query.filter_by(id=id).first()
    db.session.delete(savedPost)
    db.session.commit()
    return redirect(url_for('saved'))

@app.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        if twFollow(username):
            flash("{} followed!".format(username))
        else:
            flash("Something went wrong...")
    return redirect(request.referrer)

def twFollow(username):
    if isTwitterUser(username):
        try:
            follow = twitterFollow()
            follow.username = username
            follow.followers.append(current_user)
            db.session.add(follow)
            db.session.commit()
            return True
        except:
            flash("Couldn't follow {}. Maybe you are already following!".format(username))
            return False
    else:
        flash("Something went wrong... try again")
        return False

@app.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        if twUnfollow(username):
            flash("{} unfollowed!".format(username))
        else:
            flash("Something went wrong...")
    return redirect(request.referrer)

def twUnfollow(username):
    try:
        user = twitterFollow.query.filter_by(username=username).first()
        db.session.delete(user)
        db.session.commit()
        flash("{} unfollowed!".format(username))
    except:
        flash("There was an error unfollowing the user. Try again.")
    return redirect(request.referrer)

@app.route('/following')
@login_required
def following():
    form = EmptyForm()
    followCount = len(current_user.twitter_following_list())
    accounts = current_user.twitter_following_list()
    return render_template('following.html', accounts = accounts, count = followCount, form = form)

@app.route('/search', methods=['GET', 'POST'])
@login_required
def search():
    form = SearchForm()
    parsedResults = []
    if form.validate_on_submit():
        user = form.username.data
        r = requests.get("{instance}search?f=users&q={usern}".format(instance=nitterInstance, usern=user.replace(" ", "+")))
        html = BeautifulSoup(str(r.content), "lxml")
        results = html.body.find_all('a', attrs={'class':'tweet-link'})
        if results:
            parsedResults = [s['href'].replace("/", "") for s in results]
            return render_template('search.html', form = form, results = parsedResults)
        else:
            flash("User {} not found...".format(user))
            return render_template('search.html', form = form, results = parsedResults)
    else:
        return render_template('search.html', form = form)

@app.route('/user/<username>')
@login_required
def user(username):
    isTwitter = isTwitterUser(username)    
    if not isTwitter:
        flash("This user is not on Twitter.")
        return redirect( url_for('error', errno="404"))
    
    posts = []
    posts.extend(getPosts(username))
    form = EmptyForm()
    user = User.query.filter_by(username=username).first()
    if not posts:
        profilePic = avatarPath
    else:
        profilePic = posts[0].userProfilePic
    return render_template('user.html', user=user, posts=posts, profilePic = profilePic, form=form)

#########################
#### Youtube Logic ######
#########################
@app.route('/youtube', methods=['GET', 'POST'])
@login_required
def youtube():
    followCount = len(current_user.youtube_following_list())
    start_time = time.time()
    ids = current_user.youtube_following_list()
    videos = getYoutubePosts(ids)
    if videos:
        videos.sort(key=lambda x: x.date, reverse=True)
    print("--- {} seconds fetching youtube feed---".format(time.time() - start_time))
    return render_template('youtube.html', videos=videos, followCount=followCount)

@app.route('/ytfollowing', methods=['GET', 'POST'])
@login_required
def ytfollowing():
    form = EmptyForm()
    channelList = current_user.youtube_following_list()
    channelCount = len(channelList)
    
    return render_template('ytfollowing.html', form=form, channelList=channelList, channelCount=channelCount)

@app.route('/ytsearch', methods=['GET', 'POST'])
@login_required
def ytsearch():
    form = ChannelForm()
    button_form = EmptyForm()
    if form.validate_on_submit():
        channels = []
        videos = []

        searchTerm = form.channelId.data
        search = YoutubeSearch(searchTerm)
        chnns = search.channels_to_dict()
        vids = search.videos_to_dict()
        
        for v in vids:
            videos.append({
                'channelName':v['channel'],
                'videoTitle':v['title'],
                'description':Markup(v['long_desc']),
                'id':v['id'],
                'videoThumb': v['thumbnails'][-1],
                'channelUrl':v['url_suffix'],
                'channelId': v['channelId'],
                'views':v['views'],
                'timeStamp':v['publishedText']
            })

        for c in chnns:
            channels.append({
                'username':c['name'],
                'channelId':c['id'],
                'thumbnail':'https:{}'.format(c['thumbnails'][0]),
                'subCount':letterify(c['suscriberCountText'])
            })
        return render_template('ytsearch.html', form=form, btform=button_form, channels=channels, videos=videos)

    else:
        return render_template('ytsearch.html', form=form)

@app.route('/ytfollow/<channelId>', methods=['POST'])
@login_required
def ytfollow(channelId):
    form = EmptyForm()
    if form.validate_on_submit():
        r = followYoutubeChannel(channelId)            
    return redirect(request.referrer)

def followYoutubeChannel(channelId):
    channel = youtubeFollow.query.filter_by(channelId=channelId).first()
    channelData = YoutubeSearch.channelInfo(channelId, False)
    try:
        follow = youtubeFollow()
        follow.channelId = channelId
        follow.channelName = channelData[0]['name']
        follow.followers.append(current_user)
        db.session.add(follow)
        db.session.commit()
        flash("{} followed!".format(channelData[0]['name']))
        return True
    except:
        flash("Couldn't follow {}. Maybe you are already following!".format(channelData[0]['name']))
        return False

@app.route('/ytunfollow/<channelId>', methods=['POST'])
@login_required
def ytunfollow(channelId):
    form = EmptyForm()
    if form.validate_on_submit():
        r =  unfollowYoutubeChannel(channelId)
    return redirect(request.referrer)

def unfollowYoutubeChannel(channelId):
    try:
        channel = youtubeFollow.query.filter_by(channelId=channelId).first()
        db.session.delete(channel)
        db.session.commit()
        flash("{} unfollowed!".format(channel.channelName))
    except:
        print("Exception")
        flash("There was an error unfollowing the user. Try again.")
    return redirect(request.referrer)

@app.route('/channel/<id>', methods=['GET'])
@login_required
def channel(id):
    form = ChannelForm()
    button_form = EmptyForm()
    data = requests.get('https://www.youtube.com/feeds/videos.xml?channel_id={id}'.format(id=id))
    data = feedparser.parse(data.content)

    channelData = YoutubeSearch.channelInfo(id)
    return render_template('channel.html', form=form, btform=button_form, channel=channelData[1], videos=channelData[0])

@app.route('/watch', methods=['GET'])
@login_required
def watch():
    id = request.args.get('v', None)
    ydl = YoutubeDL()
    data = ydl.extract_info("{id}".format(id=id), download=False)
    if data['formats'][-1]['url'].find("manifest.googlevideo") > 0:
        flash("Livestreams are not yet supported!")
        return redirect(url_for('youtube'))

    video = {
        'title':data['title'],
        'description':Markup(data['description']),
        'viewCount':data['view_count'],
        'author':data['uploader'],
        'authorUrl':data['uploader_url'],
        'channelId': data['uploader_id'],
        'id':id,
        'averageRating': str((float(data['average_rating'])/5)*100)
    }
    return render_template("video.html", video=video)

## PROXY videos through Parasitter server to the client.
@app.route('/stream', methods=['GET'])
@login_required
def stream():
    id = request.args.get('v', None)
    if(id):
        ydl = YoutubeDL()
        data = ydl.extract_info("{id}".format(id=id), download=False)
        req = requests.get(data['formats'][-1]['url'], stream = True)
        return Response(req.iter_content(chunk_size=10*1024), content_type = req.headers['Content-Type'])
    else:
        flash("Something went wrong loading the video... Try again.")
        return redirect(url_for('youtube'))

#########################
#### General Logic ######
#########################
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='Sign In', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/export')
@login_required
#Export data into a JSON file. Later you can import the data.
def export():
    a = exportData()
    if a:
        return send_from_directory('.', 'data_export.json', as_attachment=True)
    else:
        return redirect(url_for('error/405'))

def exportData():
    twitterFollowing = current_user.following_list()
    youtubeFollowing = current_user.youtube_following_list()
    data = {}
    data['twitter'] = []
    data['youtube'] = []

    for f in twitterFollowing:
        data['twitter'].append({
            'username': f.username
        })
    
    for f in youtubeFollowing:
        data['youtube'].append({
            'channelId': f.channelId
        })

    try:
        with open('app/data_export.json', 'w') as outfile:
            json.dump(data, outfile)
        return True
    except:
        return False    

@app.route('/importdata', methods=['GET', 'POST'])
@login_required
def importdata():
    if request.method == 'POST':
        print("Post request recieved")
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            data = json.load(file)
            for acc in data['twitter']:
                if twFollow(acc['username']):
                    print("{} followed!".format(acc['username']))
                else:
                    print("Something went wrong!")
    return redirect(request.referrer)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        if isTwitterUser(form.username.data):
            flash('This is username is taken! Choose a different one.')
        else:
            user = User(username=form.username.data, email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash('Congratulations, you are now a registered user!')
            return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

@app.route('/error/<errno>')
def error(errno):
    return render_template('{}.html'.format(str(errno)))

def getTimeDiff(t):
    tweetTime = datetime.datetime(*t[:6])
    diff = datetime.datetime.now() - tweetTime

    if diff.days == 0:
        if diff.seconds > 3599:
            timeString = "{}h".format(int((diff.seconds/60)/60))
        else:
            timeString = "{}m".format(int(diff.seconds/60))
    else:
        timeString = "{}d".format(diff.days)
    return timeString

def isTwitterUser(username):
    request = requests.get('https://nitter.net/{}/rss'.format(username), timeout=5)
    if request.status_code == 404:
        return False
    return True

def getFeed(urls):
    avatarPath = "img/avatars/{}.png".format(str(random.randint(1,12)))
    feedPosts = []
    with FuturesSession() as session:
        futures = [session.get('https://nitter.net/{}/rss'.format(u.username)) for u in urls]
        for future in as_completed(futures):
            resp = future.result()
            rssFeed=feedparser.parse(resp.content)
            if rssFeed.entries != []:
                    for post in rssFeed.entries:
                        newPost = twitterPost()
                        newPost.username = rssFeed.feed.title.split("/")[1].replace(" ", "")
                        newPost.twitterName = rssFeed.feed.title.split("/")[0]
                        newPost.date = getTimeDiff(post.published_parsed)
                        newPost.timeStamp = datetime.datetime(*post.published_parsed[:6])
                        newPost.op = post.author
                        try:
                            newPost.userProfilePic = rssFeed.channel.image.url
                        except:
                            newPost.profilePicture = ""
                        newPost.url = post.link
                        newPost.content = Markup(post.description)
                        
                        if "Pinned" in post.title.split(":")[0]:
                            newPost.isPinned = True

                        if "RT by" in post.title:
                            newPost.isRT = True
                            newPost.profilePic = ""
                        else:
                            newPost.isRT = False
                            try:
                                newPost.profilePic = rssFeed.channel.image.url
                            except:
                                newPost.profilePic = avatarPath
                        feedPosts.append(newPost)
    return feedPosts

def getPosts(account):
    avatarPath = "img/avatars/{}.png".format(str(random.randint(1,12)))
    posts = []
        
    #Gather profile info.
    rssFeed = feedparser.parse('{instance}{user}/rss'.format(instance=nitterInstance, user=account))
    #Gather posts
    if rssFeed.entries != []:
        for post in rssFeed.entries:
            newPost = twitterPost()
            newPost.username = rssFeed.feed.title.split("/")[1].replace(" ", "")
            newPost.twitterName = rssFeed.feed.title.split("/")[0]
            newPost.date = getTimeDiff(post.published_parsed)
            newPost.timeStamp = datetime.datetime(*post.published_parsed[:6])
            newPost.op = post.author
            try:
                newPost.userProfilePic = rssFeed.channel.image.url
            except:
                newPost.profilePicture = ""
            newPost.url = post.link
            newPost.content = Markup(post.description)
            
            if "Pinned" in post.title.split(":")[0]:
                newPost.isPinned = True

            if "RT by" in post.title:
                newPost.isRT = True
                newPost.profilePic = ""
            else:
                newPost.isRT = False
                try:
                    newPost.profilePic = rssFeed.channel.image.url
                except:
                    newPost.profilePic = avatarPath
            posts.append(newPost)
    return posts

def getYoutubePosts(ids):
    videos = []
    ydl = YoutubeDL()
    with FuturesSession() as session:
        futures = [session.get('https://www.youtube.com/feeds/videos.xml?channel_id={id}'.format(id=id.channelId)) for id in ids]
        for future in as_completed(futures):
            resp = future.result()
            rssFeed=feedparser.parse(resp.content)
            for vid in rssFeed.entries:
                video = ytPost()
                video.date = vid.published_parsed
                video.timeStamp = getTimeDiff(vid.published_parsed)
                video.channelName = vid.author_detail.name
                video.channelId = vid.yt_channelid
                video.channelUrl = vid.author_detail.href
                video.id = vid.yt_videoid
                video.videoTitle = vid.title
                video.videoThumb = vid.media_thumbnail[0]['url']
                video.views = vid.media_statistics['views']
                video.description = vid.summary_detail.value
                video.description = re.sub(r'^https?:\/\/.*[\r\n]*', '', video.description[0:120]+"...", flags=re.MULTILINE)
                videos.append(video)
    return videos

def letterify(number):
    order = len(str(number))
    if order == 4:
        subCount = "{k}.{c}k".format(k=str(number)[0:1], c=str(number)[1:2])
    elif order == 5:
        subCount = "{k}.{c}k".format(k=str(number)[0:2], c=str(number)[2:3])
    elif order == 6:
        subCount = "{k}.{c}k".format(k=str(number)[0:3], c=str(number)[3:4])
    elif order == 7:
        subCount = "~{M}M".format(M=str(number)[0:1])
    elif order == 8:
        subCount = "~{M}M".format(M=str(number)[0:2])
    elif order >= 8:
        subCount = "{M}M".format(M=str(number)[0:3])
    else:
        subCount = str(number)

    return subCount