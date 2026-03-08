
import os
import time
import re
import json
import threading
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import platform

from playwright.sync_api import sync_playwright, Page
from bs4 import BeautifulSoup

# 创建Flask应用
app = Flask(__name__)
CORS(app)  # 启用CORS，允许跨域请求

# 全局爬虫状态
scraper_status = {
    'is_running': False,
    'progress': 0,
    'message': '',
    'reviews': [],
    'error': None
}


class JDCommentScraper:
    """京东评论爬虫 - Playwright版本"""
    
    def __init__(self):
        self.browser = None
        self.page = None
        self.is_running = True
    
    def _update_status(self, progress, message, error=None):
        """更新状态"""
        scraper_status['progress'] = progress
        scraper_status['message'] = message
        if error:
            scraper_status['error'] = error
    
    def _extract_reviews(self):
        """提取评论"""
        reviews = []
        try:
            page_content = self.page.content()
            soup = BeautifulSoup(page_content, 'html.parser')
            text_content = soup.get_text()
            
            pattern = r'([a-zA-Z0-9_*]{3,20})\s*(\d{2}-\d{2})\s*(苹果\d+[a-zA-Z]*[^，。！]*?)\s*([^0-9]{30,500}?)\s*(\d{1,4})'
            matches = re.findall(pattern, text_content, re.DOTALL)
            
            for match in matches:
                try:
                    username = match[0].strip()
                    date = match[1]
                    product_model = match[2]
                    content = re.sub(r'\s+', ' ', match[3]).strip()
                    likes = int(match[4]) if match[4].isdigit() else 0
                    
                    if len(content) > 15 and len(content) < 400:
                        reviews.append({
                            'username': username,
                            'rating': '5星',
                            'date': f'2024-{date}',
                            'product_model': product_model[:80],
                            'content': content,
                            'likes': likes
                        })
                except:
                    continue
        except:
            pass
        
        return reviews
    
    def scrape(self, product_url):
        """爬取评论"""
        playwright = None
        try:
            scraper_status['is_running'] = True
            scraper_status['error'] = None
            
            # 启动Playwright
            self._update_status(10, "初始化浏览器...")
            playwright = sync_playwright().start()
            
            self.browser = playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )
            
            context = self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            self.page = context.new_page()
            self.page.set_default_timeout(30000)
            
            self._update_status(20, "浏览器启动成功")
            
            # 访问页面
            self._update_status(30, "访问商品页面...")
            self.page.goto(product_url, wait_until='networkidle')
            time.sleep(3)
            
            if not self.is_running:
                return []
            
            # 滚动到评论区
            self._update_status(40, "滚动到评论区...")
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            time.sleep(2)
            
            # 点击大家评
            try:
                self.page.click("text='大家评'", timeout=5000)
                time.sleep(3)
            except:
                pass
            
            if not self.is_running:
                return []
            
            # 点击全部评价
            try:
                self.page.click("text='全部评价'", timeout=5000)
                time.sleep(3)
            except:
                pass
            
            self._update_status(50, "开始收集评论...")
            time.sleep(2)
            
            # 收集评论
            all_reviews = []
            previous_count = 0
            no_new_count = 0
            
            for scroll_round in range(50):
                if not self.is_running:
                    break
                
                try:
                    # 滚动
                    self.page.evaluate("window.scrollBy(0, 400)")
                    time.sleep(1)
                    
                    # 每3轮提取
                    if scroll_round % 3 == 0:
                        reviews = self._extract_reviews()
                        
                        for review in reviews:
                            exists = any(
                                r['username'] == review['username'] and 
                                r['content'][:40] == review['content'][:40]
                                for r in all_reviews
                            )
                            if not exists:
                                all_reviews.append(review)
                        
                        current_count = len(all_reviews)
                        progress = min(50 + (current_count * 50 // 100), 95)
                        self._update_status(progress, f"已收集 {current_count} 条评论")
                        
                        # 检查停止条件
                        if current_count == previous_count:
                            no_new_count += 1
                        else:
                            no_new_count = 0
                        previous_count = current_count
                        
                        if no_new_count >= 5 or current_count >= 100:
                            break
                            
                except Exception as e:
                    continue
            
            self._update_status(100, f"成功收集 {len(all_reviews)} 条评论")
            return all_reviews
            
        except Exception as e:
            self._update_status(0, f"错误: {str(e)}", str(e))
            raise
        finally:
            if self.page:
                self.page.close()
            if self.browser:
                self.browser.close()
            if playwright:
                playwright.stop()
            scraper_status['is_running'] = False


# ===== API 路由 =====

@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'message': '服务运行正常',
        'version': '1.0.0'
    })


@app.route('/scrape', methods=['POST'])
def scrape():
    """爬取评论接口
    
    请求格式:
    {
        "url": "https://item.jd.com/10141989827074.html"
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少参数: url',
                'example': '{"url": "https://item.jd.com/10141989827074.html"}'
            }), 400
        
        product_url = data['url'].strip()
        
        if not product_url.startswith('http'):
            return jsonify({
                'status': 'error',
                'message': 'URL格式不正确'
            }), 400
        
        if scraper_status['is_running']:
            return jsonify({
                'status': 'error',
                'message': '已有爬取任务在进行中',
                'progress': scraper_status['progress']
            }), 400
        
        scraper = JDCommentScraper()
        reviews = scraper.scrape(product_url)
        reviews.sort(key=lambda x: x['likes'], reverse=True)
        
        return jsonify({
            'status': 'success',
            'message': f'成功爬取 {len(reviews)} 条评论',
            'count': len(reviews),
            'data': reviews
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'爬取失败: {str(e)}',
            'error': str(e)
        }), 500


@app.route('/scrape/async', methods=['POST'])
def scrape_async():
    """异步爬取评论接口"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少参数: url'
            }), 400
        
        if scraper_status['is_running']:
            return jsonify({
                'status': 'error',
                'message': '已有爬取任务在进行中',
                'progress': scraper_status['progress']
            }), 400
        
        product_url = data['url'].strip()
        
        def background_scrape():
            try:
                scraper = JDCommentScraper()
                reviews = scraper.scrape(product_url)
                reviews.sort(key=lambda x: x['likes'], reverse=True)
                scraper_status['reviews'] = reviews
            except Exception as e:
                scraper_status['error'] = str(e)
        
        thread = threading.Thread(target=background_scrape)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'message': '爬取任务已开始',
            'progress': 0
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/scrape/status', methods=['GET'])
def scrape_status():
    """获取爬取状态"""
    return jsonify({
        'is_running': scraper_status['is_running'],
        'progress': scraper_status['progress'],
        'message': scraper_status['message'],
        'count': len(scraper_status['reviews']),
        'error': scraper_status['error']
    })


@app.route('/scrape/result', methods=['GET'])
def scrape_result():
    """获取爬取结果"""
    if scraper_status['is_running']:
        return jsonify({
            'status': 'running',
            'progress': scraper_status['progress'],
            'message': scraper_status['message']
        })
    
    if scraper_status['error']:
        return jsonify({
            'status': 'error',
            'message': scraper_status['error']
        }), 500
    
    return jsonify({
        'status': 'success',
        'count': len(scraper_status['reviews']),
        'data': scraper_status['reviews']
    })


@app.route('/scrape/stop', methods=['POST'])
def scrape_stop():
    """停止爬取"""
    scraper_status['is_running'] = False
    return jsonify({
        'status': 'success',
        'message': '已发送停止信号'
    })


@app.route('/stats', methods=['POST'])
def get_stats():
    """获取评论统计"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({
                'status': 'error',
                'message': '缺少参数: url'
            }), 400
        
        scraper = JDCommentScraper()
        reviews = scraper.scrape(url)
        
        if not reviews:
            return jsonify({
                'status': 'error',
                'message': '未获取到评论'
            }), 404
        
        total_likes = sum(r['likes'] for r in reviews)
        max_likes = max(r['likes'] for r in reviews)
        avg_likes = total_likes / len(reviews)
        
        return jsonify({
            'status': 'success',
            'total_comments': len(reviews),
            'total_likes': total_likes,
            'max_likes': max_likes,
            'avg_likes': round(avg_likes, 2),
            'top_comments': reviews[:5]
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/', methods=['GET'])
def index():
    """API文档"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>京东评论爬取 API</title>
        <style>
            body { font-family: Arial; margin: 20px; background: #f5f5f5; }
            .container { max-width: 900px; margin: 0 auto; }
            h1 { color: #333; }
            .endpoint { background: white; padding: 20px; margin: 15px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            code { background: #e8e8e8; padding: 3px 8px; border-radius: 3px; font-family: monospace; }
            h2 { color: #0066cc; font-size: 18px; }
            p { line-height: 1.6; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 京东评论爬取 API 文档</h1>
            
            <div class="endpoint">
                <h2>1. 健康检查</h2>
                <p><strong>GET</strong> /health</p>
                <p>检查服务是否运行正常</p>
            </div>
            
            <div class="endpoint">
                <h2>2. 爬取评论 (同步)</h2>
                <p><strong>POST</strong> /scrape</p>
                <p><strong>请求体:</strong></p>
                <code>{"url": "https://item.jd.com/10141989827074.html"}</code>
            </div>
            
            <div class="endpoint">
                <h2>3. 爬取评论 (异步)</h2>
                <p><strong>POST</strong> /scrape/async</p>
                <p>后台运行爬取</p>
            </div>
            
            <div class="endpoint">
                <h2>4. 获取状态</h2>
                <p><strong>GET</strong> /scrape/status</p>
                <p>获取当前爬取任务的状态</p>
            </div>
            
            <div class="endpoint">
                <h2>5. 获取结果</h2>
                <p><strong>GET</strong> /scrape/result</p>
                <p>获取爬取完成后的结果</p>
            </div>
        </div>
    </body>
    </html>
    """


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )
