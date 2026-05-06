class CTest:
    def __init__(self, node_cfg, process_comm, proc_modules_obj, progress_callback):
        self.node_cfg = node_cfg
        self.process_comm = process_comm
        self.proc_modules_obj = proc_modules_obj
        self.progress_callback = progress_callback

    def sum(self, params):
        """
        求和操作
        @param params: 包含 'a' 和 'b' 的字典
        @return: None (结果通过 progress_callback 报告)
        """
        try:
            a = params.get("a")
            b = params.get("b")
            
            # 报告开始处理
            self.progress_callback(10, f"开始处理求和: a={a}, b={b}")
            
            # 执行计算
            result = a + b + 1
            print(f"demo 0.0.0 - 获取到参数a: {a}, b: {b}")
            print(f"demo 0.0.0 - 执行{a}+{b}+1 = {result}")
            
            # 报告进度（50%）
            self.progress_callback(50, f"计算完成，结果: {result}")
            
            # 报告成功完成，将结果通过回调传出
            # 注意：结果数据可以通过 deal_msg 或其他机制传递
            self.progress_callback(100, f"求和操作成功完成。结果: {result}", "ok")
            
        except Exception as e:
            # 报告错误
            self.progress_callback(-1, f"求和操作失败: {str(e)}", "failed")
            raise e

    def divide(self, params):
        """
        除法操作示例
        @param params: 包含 'numerator' 和 'denominator' 的字典
        @return: None (结果通过 progress_callback 报告)
        """
        try:
            numerator = params.get("numerator")
            denominator = params.get("denominator")
            
            self.progress_callback(10, f"开始处理除法: {numerator} / {denominator}")
            
            if denominator == 0:
                raise ValueError("除数不能为0")
            
            result = numerator / denominator
            
            self.progress_callback(100, f"除法操作成功。结果: {result}", "ok")
            
        except Exception as e:
            self.progress_callback(-1, f"除法操作失败: {str(e)}", "failed")
            raise e

