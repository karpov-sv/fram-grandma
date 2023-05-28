#!/usr/bin/env python3

import os, sys, glob, time
import numpy as np
import requests

# Horizon from file
def get_horizon(filename='/etc/rts2/horizon', min_alt=10.0):
    if not os.path.exists(filename):
        def fn(x):
            return x*0 + min_alt

        return fn

    az, alt = np.loadtxt(filename, skiprows=3, unpack=True)

    if az[0] > 0:
        az = np.concatenate([[0], az])
        alt = np.concatenate([[alt[0]], alt])

    if az[-1] < 360:
        az = np.concatenate([az, [360]])
        alt = np.concatenate([alt, [alt[-1]]])

    alt[alt<min_alt] = min_alt

    def fn(x):
        return np.interp(x, az, alt)

    return fn

# Sending an e-mail witn attachments
def send_email(message, to='karpov.sv@gmail.com', sender='focuser@localhost', subject=None, attachments=[]):
    import smtplib
    from email.message import Message
    from email.mime.audio import MIMEAudio
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email import encoders
    import mimetypes

    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(message))

        for filename in attachments:
            with open(filename, 'rb') as fp:
                ctype, encoding = mimetypes.guess_type(filename)
                if ctype is None or encoding is not None:
                    # No guess could be made, or the file is encoded (compressed), so
                    # use a generic bag-of-bits type.
                    ctype = 'application/octet-stream'

                maintype, subtype = ctype.split('/', 1)

                if maintype == 'text':
                    data = MIMEText(fp.read(), _subtype=subtype)
                elif maintype == 'image':
                    data = MIMEImage(fp.read(), _subtype=subtype)
                elif maintype == 'audio':
                    data = MIMEAudio(fp.read(), _subtype=subtype)
                else:
                    data = MIMEBase(maintype, subtype)
                    data.set_payload(fp.read())
                    encoders.encode_base64(data)

            data.add_header('Content-Disposition', 'attachment', filename=os.path.split(filename)[-1])
            msg.attach(data)

    else:
        msg = MIMEText(message)

    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to

    s = smtplib.SMTP('localhost')
    s.starttls()
    s.sendmail(sender, to, msg.as_string())
    s.quit()

def send_telegram(message, token=None, chatid=None, attachments=[]):
    if token and chatid:
        requests.get('https://api.telegram.org/bot' + token + '/sendMessage',
                     data = {'chat_id': chatid, 'parse_mode': 'Markdown', 'text': message})

        if attachments:
            for filename in attachments:
                with open(filename, 'rb') as f:
                    content = f.read()
                    requests.post('https://api.telegram.org/bot' + token + '/sendPhoto',
                                  data = {'chat_id': chatid},
                                  files = {'photo': content})
