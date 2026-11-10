# TikTok Live Reader

This add-on connects to TikTok live streams and extracts information in real time. It uses the TikTokLive Python library to access a specific live stream. The following features are supported:

* Logging extracted data into text files created in the `Documents\TikTok live` folder.
* Archiving completed live sessions in a `Backups` subfolder, organized by date, time, and host.
* Tracking events: comments, new followers, gifts, likes, guest requests, shares, and visitors.
* Reposts, new fan club members, and pauses of the live are also logged.
* An events file that can record multiple types of data simultaneously.
* Audio notifications for selected events, such as new comments, gifts, etc.
* Stream statistics: displays current viewers, total session visitors, total likes, new followers, and diamonds collected. It also shows the live duration and the number of comments, shares, and gifts.
* Top Gifters leaderboard: ranks users from most active to least active based on diamonds sent.
* Top Likers leaderboard: ranks users based on their total likes during the stream.
* Record live streams as video or audio files, saved by default in the `Videos\TikTok live` folder.

---

## Documentation

* [English Documentation](https://stefantsvyatkov.github.io/TikTokLiveReader/addon/doc/en/readme.html)
* [Bulgarian Documentation](https://stefantsvyatkov.github.io/TikTokLiveReader/addon/doc/bg/readme.html)
* [Indonesian Documentation](https://stefantsvyatkov.github.io/TikTokLiveReader/addon/doc/id/readme.html)

## License

Distributed under the **GNU General Public License, version 2 or later**.
The bundled TikTokLive library and its dependencies keep their own licenses (TikTokLive: AGPL-3.0 with additional permissions; zoneinfo from Python: PSF License); their license files are included in the add-on.
