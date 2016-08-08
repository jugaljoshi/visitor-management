from django.http import HttpResponse, HttpResponseForbidden, HttpRequest, HttpResponseNotAllowed
import simplejson
import json
from django.views.generic import View, TemplateView
from visitorManagement.mapi.utils import MapiErrorCodes, JSONResponse, mapi_mandatory_parameters, \
    get_visitor_all_fields, \
    get_base_image_url
from django.conf import settings
import logging
from visitorManagement.mapi.models import Member, Visitor, WorkBookType, WorkBook
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from visitorManagement.mapi.request_handler import make_token, mapi_authenticate
from django.shortcuts import get_list_or_404, get_object_or_404
from PIL import Image
import json
import datetime


class BaseMapiView(View):
    def __init__(self, **kwargs):
        super(BaseMapiView, self).__init__(**kwargs)
        self.protocol = None
        self.member = None
        self.current_delivery_address = None

    @classmethod
    def render_to_response(cls, response=None, status=0, message='success'):
        ret_dict = {'status': status,
                    'message': message,
                    'response': response if response else None
                    }
        logging.info(ret_dict)
        return JSONResponse(json.dumps(ret_dict))

    @classmethod
    def render_error_response(cls, mapi_error_code, message=None, response=None):
        ret_dict = {'status': mapi_error_code.code,
                    'message': message,
                    'response': response if response else None
                    }
        logging.info(ret_dict)
        return JSONResponse(json.dumps(ret_dict))

    def dispatch(self, request, *args, **kwargs):
        if not settings.DEBUG and not request.is_secure():
            logging.debug("HTTPS check failed, returning HTTP 403")
            return HttpResponseForbidden()

        self.protocol = request.is_secure() and 'https' or 'http'
        self.member = request.user
        return super(BaseMapiView, self).dispatch(request, *args, **kwargs)

    def get_validated_json(self, request_data, key):
        try:
            return json.loads(request_data.get(key))
        except (ValueError, TypeError):
            return self.render_error_response(MapiErrorCodes.INVALID_FIELD, "{} is not a valid JSON object".format(key))


class LoginView(BaseMapiView):
    def post(self, request):

        member = None
        email = request.POST['email']
        password = request.POST['password']
        try:
            member = Member.objects.get(email=email, password=password)
        except Member.DoesNotExist:
            logging.debug('Member does not exit for email %s' % email)
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Email-Id or password is wrong!')

        if not member or not isinstance(member, Member):
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Email-Id or password is wrong!')
        if not bool(member.is_active):
            return BaseMapiView.render_to_response()
        token = make_token(member)
        logging.debug('Successfully logged in the user = %s', member.id)
        return BaseMapiView.render_to_response({'auth_token': token})

    @csrf_exempt
    @method_decorator(mapi_mandatory_parameters('email', 'password'))
    def dispatch(self, request, *args, **kwargs):
        return super(LoginView, self).dispatch(request, *args, **kwargs)


class RegistrationView(BaseMapiView):
    def post(self, request):
        email = request.POST['email']
        try:
            member = Member.objects.get(email=email)
        except Member.DoesNotExist:
            return self.do_register_member(request)

        if member:
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Email-Id already exit.')
        else:
            return self.do_register_member(request)

    def do_register_member(self, request):
        member = Member.objects.create(email=request.POST['email'],
                                       password=request.POST['password'],
                                       name=request.POST['name'],
                                       mobile_no=request.POST['mobile_no'],
                                       package=request.POST['package'],
                                       address=request.POST['address'])
        token = make_token(member)
        logging.debug('Successfully registered %s', member.id)
        return BaseMapiView.render_to_response({'auth_token': token})

    @csrf_exempt
    @method_decorator(mapi_mandatory_parameters('email', 'password', 'name', 'mobile_no', 'package', 'address'))
    def dispatch(self, request, *args, **kwargs):
        return super(RegistrationView, self).dispatch(request, *args, **kwargs)


class VisitorView(BaseMapiView):
    '''
    DateFormat dateFormat = new SimpleDateFormat("yyyy/MM/dd HH:mm:ss");
    Date date = new Date();
    System.out.println(dateFormat.format(date));


    DateFormat dateFormat = new SimpleDateFormat("yyyy/MM/dd HH:mm:ss");
    Calendar cal = Calendar.getInstance();
    System.out.println(dateFormat.format(cal.getTime()));
    '''

    TIME_FORMAT = '%Y%m%d %H:%M:%S'

    @method_decorator(mapi_mandatory_parameters('wb_id'))
    def get(self, request):
        member = request.user
        # member = get_object_or_404(Member, id=1) # todo remove this
        workbook = get_object_or_404(WorkBook, id=request.GET['wb_id'])
        workbook_type = workbook.wb_type
        #workbook_type = get_object_or_404(WorkBookType, id=request.GET['wb_id'])
        workbook_field_options = workbook_type.mandatory_fields
        workbook_field_options_list = workbook_field_options.split(',')
        workbook = get_object_or_404(WorkBook, member=member, wb_type=workbook_type)
        if not workbook:
            return BaseMapiView.render_error_response(MapiErrorCodes.NO_VISITOR_EXIT,
                                                      'Workbook does\'t exits for given type')

        visitors = Visitor.object.get_all_active_visitor(workbook)

        if not visitors:
            return BaseMapiView.render_error_response(MapiErrorCodes.NO_VISITOR_EXIT,
                                                      'No visitors for given workbook')
        response = []
        visitor_field = Visitor.object.get_all_field_names()  # get_visitor_all_fields()
        needed_fields = set(visitor_field).intersection(workbook_field_options_list)
        for visitor in visitors:
            d = dict()
            while needed_fields:
                field_name = needed_fields.pop()
                field_value = visitor[field_name]
                if isinstance(field_value, datetime.datetime):
                    field_value = field_value.strftime("%I.%M %p")

                if field_name in ['photo', 'signature'] and field_value:
                    field_value = '%s%s' % (get_base_image_url(), field_value)

                d.update({str(field_name): field_value})
            if d:
                response.append(d)
        if response:
            return BaseMapiView.render_to_response(response)
        else:
            return BaseMapiView.render_error_response(MapiErrorCodes.NO_VISITOR_EXIT,
                                                      'No visitors for given workbook')

    def post(self, request):
        params = request.POST.get('params')
        if not params:
            return BaseMapiView.render_error_response(MapiErrorCodes.INVALID_FIELD,
                                                      'Missing params in request')
        params = json.loads(params)
        wb_id = params.get('wb_id')
        if not wb_id:
            return BaseMapiView.render_error_response(MapiErrorCodes.INVALID_FIELD,
                                                      'Missing work book Id in request')

        workbook = get_object_or_404(WorkBook, id=wb_id)
        workbook_type = workbook.wb_type
        workbook_mandatory_fields = workbook_type.mandatory_fields
        workbook_mandatory_fields_list = workbook_mandatory_fields.split(',')
        visitor_field = Visitor.object.get_all_field_names()
        needed_fields = set(visitor_field).intersection(workbook_mandatory_fields_list)

        if 'photo' in needed_fields and not request.FILES.get('photo'):
            needed_fields.remove('photo')
            return BaseMapiView.render_error_response(MapiErrorCodes.INVALID_FIELD,
                                                      "Missing field photo in request")

        if 'signature' in needed_fields and not request.FILES.get('signature'):
            needed_fields.remove('signature')
            return BaseMapiView.render_error_response(MapiErrorCodes.INVALID_FIELD,
                                                      "Missing field signature in request")

        '''
        request_dict = request.__getattribute__(request.method)
        for param in needed_fields:
            if not request_dict.get(param, None):
                return BaseMapiView.render_error_response(MapiErrorCodes.INVALID_FIELD,
                                                          "Missing field '%s' in request" % param)
        '''

        name = params.get('name')
        mobile_no = params.get('mobile_no')
        vehicle_no = params.get('vehicle_no')
        from_place = params.get('from_place')
        destination_place = params.get('destination_place')
        from django.utils import timezone
        in_time = params.get('in_time')
        in_time_datetime = None
        if in_time:
            in_time_datetime = timezone.make_aware(datetime.datetime.strptime(in_time, self.TIME_FORMAT),
                                                   timezone.get_default_timezone())
            # in_time_datetime = datetime.datetime.strptime(in_time, self.TIME_FORMAT)

        out_time = params.get('out_time')
        out_time_datetime = None
        if out_time:
            out_time_datetime = timezone.make_aware(datetime.datetime.strptime(out_time, self.TIME_FORMAT),
                                                    timezone.get_default_timezone())
            # out_time_datetime = datetime.datetime.strptime(out_time, self.TIME_FORMAT)

        photo = request.FILES.get('photo')
        signature = request.FILES.get('signature')

        import ipdb; ipdb.set_trace()
        import time
        time_stamp = time.time()
        try:
            if photo:
                photo = Image.open(photo)
                # photo.verify()
                (width, height) = photo.size
                if width > 125 or height > 125:
                    photo = photo.resize((125, 125), Image.ANTIALIAS)
                visitor_img_path = settings.MEDIA_ROOT + '/uploads/member_photos/' + str(time_stamp) + '_' + wb_id+'.png'
                photo.save(visitor_img_path)

            if signature:
                signature = Image.open(signature)
                # signature.verify()
                (width, height) = signature.size
                if width > 125 or height > 125:
                    signature = signature.resize((125, 125), Image.ANTIALIAS)
                signature_img_path = settings.MEDIA_ROOT + '/uploads/signature_photos/' + str(time_stamp) + '_' + wb_id+'.png'
                signature.save(signature_img_path)

        except IOError as e:
            logging.error(e.message)
            return BaseMapiView.render_error_response(MapiErrorCodes.INVALID_FIELD,
                                                      'Uploaded image not in correct format')

        try:
            visitor = Visitor.object.create(member=request.user,
                                            workbook=workbook,
                                            name=name,
                                            mobile_no=mobile_no,
                                            vehicle_no=vehicle_no,
                                            from_place=from_place,
                                            destination_place=destination_place,
                                            in_time=in_time_datetime,
                                            out_time=out_time_datetime,
                                            photo='uploads/member_photos/' + str(time_stamp) + '_' + wb_id + '.png',
                                            signature='uploads/signature_photos/' + str(time_stamp) + '_' + wb_id + '.png')
        except Exception as e:
            logging.error(e.message)
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Unable to create visitor, Please try again later.')
        if visitor:
            return BaseMapiView.render_to_response()
        else:
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Unable to create visitor!')

    @csrf_exempt
    @method_decorator(mapi_authenticate(optional=False))
    def dispatch(self, request, *args, **kwargs):
        return super(VisitorView, self).dispatch(request, *args, **kwargs)


class WorkBookView(BaseMapiView):
    def get(self, request):
        member = request.user

        workbooks = WorkBook.objects.filter(member=member)
        if workbooks:
            return self.generate_workbook_response(workbooks)
        else:
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'No Workbook available for member.'
                                                      ' Please create one!')

    def generate_workbook_response(self, workbooks):
        workbooks_list = []
        for workbook in workbooks:
            workbooks_list.append({
                'wb_name': workbook.wb_name,
                'wb_type_id': str(workbook.wb_type.id),
                'wb_img_url': ''.join(
                    [get_base_image_url(), workbook.wb_type.wb_icon.name]) if workbook.wb_type.wb_icon.name else '',
            })
        return BaseMapiView.render_to_response(workbooks_list)

    @method_decorator(mapi_mandatory_parameters('wb_name', 'mandatory_fields', 'wb_type_id'))
    def post(self, request):

        member = request.user
        workbook_type = None
        try:
            workbook_type = WorkBookType.objects.get(id=request.POST['wb_type_id'])
        except WorkBookType.DoesNotExist:
            return BaseMapiView.render_error_response(
                MapiErrorCodes.GENERIC_ERROR, 'Workbook type doesn\'t exits!')

        if not workbook_type:
            return BaseMapiView.render_error_response(
                MapiErrorCodes.GENERIC_ERROR, 'Workbook type doesn\'t exits!')

        needed_fields = self.getValidVisitorMandatoryFields(request.POST['mandatory_fields'])
        if not needed_fields:
            # In-case someone post invalid fields via postman client
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR, 'Entered fields are not valid!')

        mandatory_fields = ','.join(needed_fields)
        workbook_type.mandatory_fields = mandatory_fields
        workbook_type.save()

        workbook = None
        try:
            workbook = WorkBook.objects.create(wb_name=request.POST['wb_name'],
                                               wb_type=workbook_type,
                                               member=member)
        except:
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Unable to create Workbook!')

        if workbook:
            return BaseMapiView.render_to_response()
        else:
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'Unable to create Workbook!')

    def getValidVisitorMandatoryFields(self, post_visitor_fields):
        visitor_all_fields = get_visitor_all_fields()
        post_visitor_fields_list = post_visitor_fields.split(',')
        needed_fields = set(visitor_all_fields).intersection(post_visitor_fields_list)
        return needed_fields

    @csrf_exempt
    @method_decorator(mapi_authenticate(optional=False))
    def dispatch(self, request, *args, **kwargs):
        return super(WorkBookView, self).dispatch(request, *args, **kwargs)


class WorkBookTypeView(BaseMapiView):
    def get(self, request):
        workbooks_types = WorkBookType.objects.filter()

        if workbooks_types:
            return self.generate_workbook_type_response(workbooks_types)
        else:
            return BaseMapiView.render_error_response(MapiErrorCodes.GENERIC_ERROR,
                                                      'No workbook type configured, Please'
                                                      ' contact administrator!')

    def generate_workbook_type_response(self, workbooks_types):
        workbooks_type_list = []
        rect_dict = {}
        for wb_type in workbooks_types:
            workbooks_type_list.append({
                'wb_type': wb_type.type,
                'wb_type_id': str(wb_type.id)
            })

        rect_dict['wb_types'] = workbooks_type_list

        rect_dict['mandatory_fields'] = get_visitor_all_fields()
        return BaseMapiView.render_to_response(rect_dict)

    # @method_decorator(mapi_authenticate(optional=False))
    def dispatch(self, request, *args, **kwargs):
        return super(WorkBookTypeView, self).dispatch(request, *args, **kwargs)


'''


            # format = image.format
            # s_img.save(os.path.join(s_dir,os.path.basename(infile)),"JPEG",quality=80,optimize=True,progressive=True)
            # _file, ext = os.path.splitext(infile)
'''


class SearchView(BaseMapiView):

    def get(self, request):
        member = request.user
        name = request.GET['name']
        names = Visitor.object.filter(name__startswith=name, member=member)[:5]
        return BaseMapiView.render_to_response({'names': names})


    @method_decorator(mapi_mandatory_parameters('name'))
    #@method_decorator(mapi_authenticate(optional=False))
    def dispatch(self, request, *args, **kwargs):
        return super(SearchView, self).dispatch(request, *args, **kwargs)