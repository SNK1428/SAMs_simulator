import sys

from queue import Queue
from abc import ABC, abstractmethod
from typing import final
import time

import numpy as np
from datetime import datetime
from sklearn.model_selection import KFold#导入切分训练集、测试集模块
from sklearn.model_selection import cross_val_score, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier

from utils import grid_param_builder, load_iris_shuffle

class general_model(ABC):
    '''用于进行基于交叉验证的超参数筛选的抽象类'''
    def __init__(self, round_max = 5, reserve_best_model_size = 50, output_interval =  0.1, best_clf = None, best_clf_params = None) -> None:
        self.round_max = round_max                          # 验证最优集合的轮数
        self.clfs = Queue(maxsize=reserve_best_model_size)                 # 记录的前若干个分类器（先进先出）
        self.params = Queue(maxsize=reserve_best_model_size)               # 记录的前若干个分类器对应的超参数（先进先出）
        self.best_clf = best_clf
        self.best_clf_params = best_clf_params
        self.cv = KFold(n_splits=5, shuffle=True, random_state=datetime.now().microsecond)  # 交叉验证参数
        self.grid_params = list()
        self.grid_results = list()
        self.residual_each_param = list()       # 每个超参数的残差
        self.params_used = list()               # 每个使用过的超参数
        self.output_bar_interval = output_interval       # 打印间隔（范围 0-1 float）

    @abstractmethod
    def _cross_valid_mtd(self, clf, x_data : np.ndarray, y_data : np.ndarray) -> float:
        '''交叉验证方法'''
        pass

    @abstractmethod
    def _param_filter(self, param : np.ndarray) -> np.ndarray:
        '''超参数过滤核心方法'''
        pass

    @abstractmethod        
    def _build_clf(self, param : np.ndarray):
        '''依据超参数构建模型'''
        pass

    @final
    def __param_filter_inner(self, param_list : np.ndarray) -> np.ndarray:
        '''超参数过滤：去除其中的不合理超参数组合，并且使得其变为一个n*m数组，适应模型超参数遍历'''
        if len(param_list.shape) > 1:
            for i in range(len(param_list)):
                param_list[i] = self._param_filter(param_list[i])
            return np.unique(param_list, axis=0)
        return param_list[:,np.newaxis]

    @final
    def __find_best_clf(self, x_data : np.ndarray, y_data:np.ndarray) -> None:
        r2_best = -sys.maxsize
        actual_model_cnt = 0            # 此处保存的实际模型计数
        while not self.params.empty():
            residuals = 0
            clf = self.clfs.get()
            for round in range(self.round_max):
                residuals += self._cross_valid_mtd(clf, x_data, y_data)
            if(residuals >= r2_best):
                self.best_clf = clf
                self.best_clf_params = self.params.get()
            else:
                self.params.get()
            actual_model_cnt+=1
        if(self.best_clf is None):
            print('FATAL : no best model found')
        print("Best model search : finished, search model total : %s \r" %(actual_model_cnt))
    
    def fit(self, x_data : np.ndarray, y_data : np.ndarray, param_list : np.ndarray) -> None:
        '''拟合具有最优参数的模型 param_list为字符串数组'''
        def record_best(clf, param : np.ndarray, r2_current: float, best_r2: float) -> float:
            '''记录最优超参数，并且记录其相应的r2值'''
            if(r2_current > best_r2):
                if(self.clfs.full()):
                    self.params.get()
                    self.clfs.get()
                self.params.put(param)
                self.clfs.put(clf)
                return r2_current
            return best_r2

        def training(x_data : np.ndarray, y_data : np.ndarray, param:np.ndarray, best_r2 = -sys.maxsize) -> float:
            '''训练函数'''
            clf = self._build_clf(param)
            # print(clf.optimizer)
            try :
                residuals = self._cross_valid_mtd(clf, x_data, y_data)
                self.residual_each_param.append(residuals)              # 记录每个超参数的模型的残差
            except ValueError:
                print('fit failed with params: ', param,', model: ', clf)
                self.residual_each_param.append(-sys.maxsize)           # 记录每个超参数的模型的残差
                return best_r2      # 有时候超参数太烂会导致交叉验证失败，返回ValueError异常，此时跳过这个回合
            return record_best(clf, param, residuals, best_r2)
    
        # 预处理超参数
        original_param_size = len(param_list)
        param_list = self.__param_filter_inner(param_list)
        print('Actual used params size :', param_list.shape[0], ', original params size :', original_param_size, 'param number :', param_list.shape[1])
        self.params_used = param_list
        # 训练
        if param_list.shape[1] > 1:
            best_r2 = -sys.maxsize
            process_cnt = 0                                 # 进度计数器
            process_num = self.output_bar_interval        # 打印间隔阈值
            for param in param_list:
                best_r2 = training(x_data, y_data, param, best_r2)
                # 进度更新
                process_cnt += 1
                if(process_cnt/len(param_list) > process_num):
                    sys.stdout.write("Search process : %0.3f %%\r" % (process_cnt/len(param_list)*100))
                    sys.stdout.flush()
                    process_num += self.output_bar_interval
            # 完成参数搜索
            print("Search process : finished \r")
        elif param_list.shape[1] == 1:
            training(x_data, y_data, param_list[:, 0])
        # 训练完成后，从较优的数据中选最好的那个，并记录
        # self.__find_best_clf(x_data, y_data)
    
    @final
    def return_full_model(self, actual_params_list:list):
        '''通过参数构建实际模型'''
        model_list = []
        for params in actual_params_list:
            model_list.append(self._build_clf(np.array(params)))
        return model_list

    @final
    def get_best_clf(self):
        '''获取最优拟合器，和其相应的超参数'''
        return self.best_clf

    @final
    def get_best_params(self) :
        '''获取最优拟合器对应的超参数'''
        return self.best_clf_params

    @final
    def get_residual_param(self, seq = 0) -> np.ndarray:
        '''获取实际使用的超参数-残差联合体，按残差值大小排序， seq：结果排列顺序， 默认(0)倒序，其它数值为正序'''
        fit_results = np.array(self.residual_each_param.copy(), dtype=str)[:, np.newaxis]
        # print(self.params_used)
        param_residual_arr = np.concatenate((self.params_used.copy(), fit_results), axis=1)
        if(seq == 0):
            return  param_residual_arr[np.argsort(param_residual_arr[:, -1])[::-1]]
        else:
            return  param_residual_arr[np.argsort(param_residual_arr[:, -1])]

    @final
    def save_residual_param(self, path : str, seq = 0) -> None:
        '''存储实际使用的超参数和与其对应的残差(残差视cross_vali方法而定)， seq：结果排列顺序， 默认(0)倒序，其它数值为正序'''
        print("result is saved to path :", path)
        np.savetxt(path, self.get_residual_param(seq), fmt='%s', delimiter='\t')

#-----------------------------------------------------------------
# 使用示例
class demo_knn(general_model):
    def _cross_valid_mtd(self, clf, x_data: np.ndarray, y_data: np.ndarray) -> float:
        return float(cross_val_score(clf, x_data, y_data, cv=self.cv, scoring='r2').mean())

    def _param_filter(self, param: np.ndarray) -> np.ndarray:
        if param[4] != 'minkowski':
            param[5] = '0'
        return param
        
    def _build_clf(self, params : np.ndarray) -> KNeighborsClassifier:
        if(params[4] == 'minkowski'):
            return KNeighborsClassifier(
                n_neighbors=int(params[0]),weights=params[1],algorithm=params[2], 
                leaf_size=int(params[3]), metric=params[4], p=int(params[5]), n_jobs=-1)
        else:
            return KNeighborsClassifier(
                n_neighbors=int(params[0]),weights=params[1],algorithm=params[2], 
                leaf_size=int(params[3]), metric=params[4], n_jobs=-1)
    
    def predict(self, x_data: np.ndarray, y_data: np.ndarray) -> np.ndarray:
        '''预测数据'''
        self.best_clf.fit(x_data, y_data)
        predict_val = self.best_clf.predict(x_data)
        if(len(y_data.shape) == 1):
            return np.concatenate((predict_val[:,np.newaxis], y_data[:, np.newaxis]), axis=1)
        else:
            return np.concatenate((predict_val, y_data), axis=1)

def demo():
    '''示例方法：KNN对鸢尾花集预测'''
    # 超参数列表
    knn_param_range = [
        [3,4,5,6,7],                                            # n_neighbors 近邻邻居
        ['uniform','distance'],                                 # weights 距离权重
        ['ball_tree', 'kd_tree'],                               # algorithm 距离权重
        [30,50,70,100],                                         # leaf_size kd/ball树才有
        ['euclidean', 'minkowski','manhattan','chebyshev'],     # metric https://blog.csdn.net/weixin_44607126/article/details/102598096
        [1,2]                                                   # p(用于minkowski) 1 曼哈顿距离 2 欧
    ]
    b_time = time.time() 
    iris_x, iris_y = load_iris_shuffle()
    param_list = grid_param_builder(knn_param_range)
    np.random.shuffle(param_list)
    knn_model = demo_knn()
    knn_model.fit(iris_x, iris_y, param_list)
    best_model = knn_model.get_best_clf()
    best_param = knn_model.get_best_params()
    knn_model.save_residual_param(sys.path[0]+'/demo_grid_search_result.txt')
    r2 = cross_val_score(best_model, iris_x, iris_y, cv=5, scoring='r2')
    print(best_param)
    print("R2 (cross vali): %0.3f (+/- %0.3f)" % (r2.mean(), r2.std() * 2))
    print('time:', time.time() - b_time)
    predict_result = cross_val_predict(best_model, iris_x, iris_y)
    print('predict result / real result :')
    merge = np.concatenate([predict_result[:, np.newaxis], iris_y[:, np.newaxis]], axis=1)
    print(merge.T)
    
    
if __name__ == "__main__":
    demo()
