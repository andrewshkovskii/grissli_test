(function () {

  String.prototype.format = function () {
    'use strict';

    var args = arguments;
    return this.replace(/\{\{|\}\}|\{(\d+)\}/g, function (m, n) {
          if (m === '{{') {
            return '{';
          }
          if (m === '}}') {
            return '}';
          }
          return typeof args[n] !== 'undefined' ? args[n] : '';
        }
    );
  };

  var paginateBy = function (array, chunk) {
    var i, j;
    var pages = [];
    for (i = 0, j = array.length; i < j; i += chunk) {
      pages.push(array.slice(i, i + chunk);)
    }
    return pages;
  };


  var blockTemplate = '<div class="col-md-12 url-block" style="background-image: url({5})" id="{6}"> <table class="table table-hover"> <tbody> <tr> <th>Статус</th> <td class="url-status">{0}</td></tr><tr> <th>URL</th> <td>{1}</td></tr><tr> <th>Содержимое тега title</th> <td class="url-title">{2}</td></tr><tr> <th>Содержимое первого тега H1</th> <td class="url-h1">{3}</td></tr><tr> <th>Первое изображение из тега img</th> <td class="url-img">{4}</td></tr><tr> <th>Отменить</th> <td><a class="cancel btn btn-link">Прервать обработку</a></td></tr></tbody> </table> </div>';
  var pageTemplate = '<li><a href="#" class="page-selector" data-page="{0}">{1}</a></li>';

  $(function () {

    var $results = $('#results');
    var urls = {};
    var pages = [];
    var currentPage = 0;
    var pageLenght = 3;
    var $pager = $('.pagination');
    var host = document.location.hostname;
    var port = document.location.port || '80';

    var redrawPaginator = function (pageIndex) {
      var selectedPage = pages[pageIndex];
      var i;

      for (var uuid in urls) {
        if (urls.hasOwnProperty(uuid)) {
          var block = urls[uuid][1];
          block.hide()
        }
      }
      for (i = 0; i < selectedPage.length; i++) {
        selectedPage[i].show();
      }
      $('.page-selector').parent().removeClass('active');
      $(".page-selector[data-page='{0}']".format(pageIndex)).parent().addClass('active');

    };

    // Создание визуального блока URL
    var createURLBlock = function (url) {
      var template = blockTemplate.format(
          url['status'],
          url['url'],
          url['title'],
          url['h1'],
          url['image_src'],
          url['image_path'],
          url['uuid']
      );
      template = $(template);
      urls[url['uuid']] = [url, template];
      $results.append(template);
      var urlsArray = [];
      for (var uuid in urls) {
        if (urls.hasOwnProperty(uuid)) {
          urlsArray.push(urls[uuid][1])
        }
      }

      pages = paginateBy(urlsArray, pageLenght);
      $('.page-selector').remove();
      for (var i = 0; i < pages.length; i++) {
        $pager.append($(pageTemplate.format(i, i + 1)))
      }
      redrawPaginator(currentPage)
    };

    // Обработчик событий пагинации
    $(document.body).on('click', '.page-selector', function (event) {
      event.preventDefault();
      var $pageSelector = $(event.target);
      currentPage = $pageSelector.data('page');
      redrawPaginator(currentPage);
    });

    // Обработчик сообщений из websocket
    var handleMessage = function (evt) {
      var data = JSON.parse(evt.data);
      var message = data['message'];
      var payload = data['payload'];
      var url = urls[payload['uuid']];
      if (message == 'status_change') {
        var status = payload['status'];
        if (url) {

          url['status'] = status;
          var template = url[1];
          var $title = template.find('.url-title');
          var $status = template.find('.url-status');
          var $h1 = template.find('.url-h1');
          var $img = template.find('.url-img');
          $status.text(status);

          if (status == 'done_parsing') {
            $h1.text(payload['h1']);
            $title.text(payload['title']);
            $img.text(payload['image_src']);
            url['h1'] = payload['h1'];
            url['title'] = payload['title'];
            url['image_src'] = payload['image_src'];
          }

          if (status == 'done') {
            template.css('background-image', 'url(' + payload['image_path'] + ')');
          }
        }
      }
      if (message == 'url_add') {
        if (!url) {
          createURLBlock(payload)
        }
      }
    };

    var ws = null;

    $.datetimepicker.setLocale('ru');
    var picker = $('#datetime').datetimepicker({
      format: 'Y-m-d H:i',
      value: new Date()
    });

    var form = $('#form');
    var urlsInputs = $('.url-input');

    // Обработчик отмены обработки
    $(document.body).on('click', '.cancel', function (event) {
      var $btn = $(event.target);
      var $parent = $btn.parents('.url-block');
      var uuid = $parent.attr('id');
      var url = urls[uuid][0];
      if (url['status'] == 'done' || url['status'] == 'error' || url['status'] == 'fail_to_cancel' || url['status'] == 'cancel') {
        alert('Невозможно отправить запрос на отмену обработки')
      } else {
        $.post('url/{0}/cancel/'.format(uuid), function (data, status, jqXHR) {
          alert('Запрос на остановку отправлен!')
        })
      }
    });

    // Список текущих URL
    $.get('url/', null, function (data, status, jqXHR) {

      for (var i = 0; i < data.length; i++) {
        var url = data[i];
        createURLBlock(url)
      }

      var ws = new WebSocket('ws://'+ host + ':' + port + '/events/');

      ws.onclose = function () {
        alert('Соединение закрыто сервером')
      };

      ws.onmessage = handleMessage;
    }, 'json');

    // Отправка данных для обработки
    form.on('submit', function (event) {
      event.preventDefault();
      var _urls = [];
      var activeUrls = 0;
      for (var uuid in urls) {
        if (urls.hasOwnProperty(uuid)) {
          var status = urls[uuid]['status'];
          if (status == 'downloading' || status == 'downloaded') {
            activeUrls += 1;
          }
          if (activeUrls >= 5) {
            alert('Нельзя начать обработку, т.к. имеются 5 необработанных URL')
          }
        }
      }
      urlsInputs.each(function (index, element) {
        var url = $(element).val();
        if (url) {
          _urls.push({'url': url})
        }
      });

      // Получаем дату в формате ISO
      var date = picker.datetimepicker('getValue');
      date = new Date(date).toISOString();
      var payload = {'urls': _urls, 'date': date};

      payload = JSON.stringify(payload);

      var message = payload['error_message'];
      if (message) {
        alert(message);
        return;
      }

      $.post('url/', payload, function (data, status, jqXHR) {
        for (var i = 0; i < data.length; i++) {
          var url = data[i];
          createURLBlock(url);
        }
      }, 'json')
    });

  });
})();
